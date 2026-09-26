// Fills as fan and patch triangles counted on the stencil; the B1 design in
// docs/phase_b1_plan.md. Compile after common.wgsl and paint_field.wgsl.
//
// Nothing is uploaded for a fill beyond what the border stage already
// retains: the vertex stage pulls the fan triangle (base, p0, p2) and the
// patch triangle (p0, p1, p2) of every curve from the 44-word curve records
// (border_compute.wgsl's input) and the run's object table. Per object the
// driver draws, in order:
//   mark        fan triangles, then patch triangles with the per-sample
//               curve test; stencil increment-wrap front / decrement-wrap
//               back under write mask 0x7F, so the low seven bits hold the
//               winding count;
//   strip mark  the border strips of the border stage's output, through the
//               surface pipeline, stencil replace 0x80 under write mask 0x80;
//   cover       fan and patch triangles with colour and no curve test (the
//               count already holds the answer per sample), then the strips
//               again through the surface or paint pipeline: stencil
//               not-equal 0, pass and depth-fail set the byte to zero, so
//               each sample paints once.
// Only the mark's patch triangles are shaded per sample, so a curved edge
// gets the same sample-rate coverage as a straight one; everything else,
// the strips included, runs at pixel rate.
// 44 f32 per curve: three 12-word records (point, fill_rgba, width, joint
// angle, base normal), density, border-active, density-capped, reserved,
// then the source RGBA.
@group(1) @binding(0) var<storage, read> patch_source: array<f32>;
// 8 f32 per object: base point, curve offset, curve count, bordered, two
// reserved words.
@group(1) @binding(1) var<storage, read> patch_objects: array<f32>;
@group(2) @binding(0) var<storage, read> paint: array<vec4f>;

// The mark's fan triangles and the whole cover run at pixel rate; only the
// mark's patch triangles carry the per-sample curve test, since the
// stencil then holds the answer per sample and the cover needs no test.
struct PatchOut {
    @builtin(position) position: vec4f,
    @location(0) color: vec4f,
    @location(1) point: vec3f,
    @location(2) normal: vec3f,
    @location(3) v_clip: f32,
    @location(4) @interpolate(perspective, sample) curve_uv: vec2f,
}

struct CoverOut {
    @builtin(position) position: vec4f,
    @location(0) color: vec4f,
    @location(1) point: vec3f,
    @location(2) normal: vec3f,
    @location(3) v_clip: f32,
}

struct CurveVertex {
    point: vec3f,
    normal: vec3f,
    rgba: vec4f,
    uv: vec2f,
    valid: bool,
}

fn source_vec3(index: u32) -> vec3f {
    return vec3f(patch_source[index], patch_source[index + 1u], patch_source[index + 2u]);
}

fn object_vec3(index: u32) -> vec3f {
    return vec3f(patch_objects[index], patch_objects[index + 1u], patch_objects[index + 2u]);
}

// Corner 0..2 is the fan triangle (base, p0, p2); 3..5 the patch triangle
// (p0, p1, p2) with the curve's own coordinates. The base is the curve's
// own record's base point (its path's first point, as the rows carry it):
// a closed subpath counts the same from any base, and an open one then
// closes through its start, the chord Phase A's fill closes it with.
fn curve_vertex(object: u32, curve: u32, corner: u32) -> CurveVertex {
    var out: CurveVertex;
    out.valid = false;
    let record = 8u * object;
    if (curve >= u32(patch_objects[record + 4u])) {
        return out;
    }
    let source = 44u * (u32(patch_objects[record + 3u]) + curve);
    let p0 = source_vec3(source);
    let p1 = source_vec3(source + 12u);
    let p2 = source_vec3(source + 24u);
    if (all(p0 == p1)) {
        // A subpath's end marker, as in fill.wgsl: emits nothing.
        return out;
    }
    out.valid = true;
    out.normal = source_vec3(source + 21u);  // the unit normal: record 1, as border_compute reads it
    out.rgba = vec4f(patch_source[source + 40u], patch_source[source + 41u],
                     patch_source[source + 42u], patch_source[source + 43u]);
    out.point = source_vec3(source + 9u);
    out.uv = vec2f(0.0, 1.0);
    if (corner == 1u) { out.point = p0; }
    else if (corner == 2u) { out.point = p2; }
    else if (corner == 3u) { out.point = p0; out.uv = vec2f(0.0, 0.0); }
    else if (corner == 4u) { out.point = p1; out.uv = vec2f(0.5, 0.0); }
    else if (corner == 5u) { out.point = p2; out.uv = vec2f(1.0, 1.0); }
    return out;
}

fn cover_out(v: CurveVertex) -> CoverOut {
    var out: CoverOut;
    if (!v.valid) {
        out.position = DISCARD_POSITION;
        return out;
    }
    out.point = v.point;
    out.normal = v.normal;
    out.color = finalize_color(v.rgba, v.point, v.normal);
    out.v_clip = compute_clip_distance(v.point);
    out.position = emit_gl_position(v.point);
    return out;
}

// The mark's fan triangles: three vertices per curve, pixel rate.
@vertex
fn vs_fan(@builtin(vertex_index) vid: u32, @builtin(instance_index) object: u32) -> CoverOut {
    return cover_out(curve_vertex(object, vid / 3u, vid % 3u));
}

// The mark's patch triangles: three vertices per curve, sample rate.
@vertex
fn vs_patch(@builtin(vertex_index) vid: u32, @builtin(instance_index) object: u32) -> PatchOut {
    let v = curve_vertex(object, vid / 3u, 3u + vid % 3u);
    var out: PatchOut;
    if (!v.valid) {
        out.position = DISCARD_POSITION;
        return out;
    }
    out.point = v.point;
    out.normal = v.normal;
    out.color = finalize_color(v.rgba, v.point, v.normal);
    out.v_clip = compute_clip_distance(v.point);
    out.curve_uv = v.uv;
    out.position = emit_gl_position(v.point);
    return out;
}

// The cover: fan and patch triangles, six vertices per curve, pixel rate;
// the stencil count decides per sample.
@vertex
fn vs_cover(@builtin(vertex_index) vid: u32, @builtin(instance_index) object: u32) -> CoverOut {
    return cover_out(curve_vertex(object, vid / 6u, vid % 6u));
}

@fragment
fn fs_mark_fan(vin: CoverOut) {
    if (vin.v_clip < 0.0) { discard; }
}

@fragment
fn fs_mark_patch(vin: PatchOut) {
    if (vin.v_clip < 0.0 || vin.curve_uv.y - vin.curve_uv.x * vin.curve_uv.x < 0.0) { discard; }
}

@fragment
fn fs_surface(vin: CoverOut) -> @location(0) vec4f {
    if (vin.v_clip < 0.0) { discard; }
    return output_color(vin.color);
}

@fragment
fn fs_paint(vin: CoverOut) -> @location(0) vec4f {
    if (vin.v_clip < 0.0) { discard; }
    return output_color(finalize_color(source_paint(vin.point), vin.point, normalize(vin.normal)));
}
