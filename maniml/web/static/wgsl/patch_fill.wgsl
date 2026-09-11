// Fills as fan and patch triangles counted on the stencil; the B1 design in
// docs/phase_b1_plan.md. Compile after common.wgsl and paint_field.wgsl.
//
// Nothing is uploaded for a fill beyond what the border stage already
// retains: the vertex stage pulls the fan triangle (base, p0, p2) and the
// patch triangle (p0, p1, p2) of every curve from the 44-word curve records
// (border_compute.wgsl's input) and the run's object table. Per object the
// driver draws, in order:
//   mark        fan and patch triangles; stencil increment-wrap front /
//               decrement-wrap back under write mask 0x7F, so the low seven
//               bits hold the winding count;
//   strip mark  the border strips of the border stage's output, through the
//               surface pipeline, stencil replace 0x80 under write mask 0x80;
//   cover       fan and patch triangles with colour, then the strips again
//               through the surface or paint pipeline: stencil not-equal 0,
//               pass and depth-fail set the byte to zero, so each sample
//               paints once.
// The patch's fragment test is evaluated per sample, so a curved edge gets
// the same sample-rate coverage as a straight one; the strips stay on the
// ordinary pipelines, where nothing needs a per-sample decision.
// 44 f32 per curve: three 12-word records (point, fill_rgba, width, joint
// angle, base normal), density, border-active, density-capped, reserved,
// then the source RGBA.
@group(1) @binding(0) var<storage, read> patch_source: array<f32>;
// 8 f32 per object: base point, curve offset, curve count, bordered, two
// reserved words.
@group(1) @binding(1) var<storage, read> patch_objects: array<f32>;
@group(2) @binding(0) var<storage, read> paint: array<vec4f>;

struct PatchOut {
    @builtin(position) position: vec4f,
    @location(0) color: vec4f,
    @location(1) point: vec3f,
    @location(2) normal: vec3f,
    @location(3) v_clip: f32,
    @location(4) @interpolate(perspective, sample) curve_uv: vec2f,
    @location(5) @interpolate(flat) is_patch: u32,
}

fn source_vec3(index: u32) -> vec3f {
    return vec3f(patch_source[index], patch_source[index + 1u], patch_source[index + 2u]);
}

fn object_vec3(index: u32) -> vec3f {
    return vec3f(patch_objects[index], patch_objects[index + 1u], patch_objects[index + 2u]);
}

fn patch_discarded() -> PatchOut {
    var out: PatchOut;
    out.position = DISCARD_POSITION;
    return out;
}

@vertex
fn vs_main(@builtin(vertex_index) vid: u32, @builtin(instance_index) object: u32) -> PatchOut {
    let record = 8u * object;
    let base = object_vec3(record);
    let curve_offset = u32(patch_objects[record + 3u]);
    let curve_count = u32(patch_objects[record + 4u]);
    if (vid >= 6u * curve_count) {
        return patch_discarded();
    }
    let source = 44u * (curve_offset + vid / 6u);
    let corner = vid % 6u;
    let p0 = source_vec3(source);
    let p1 = source_vec3(source + 12u);
    let p2 = source_vec3(source + 24u);
    if (all(p0 == p1)) {
        // A subpath's end marker, as in fill.wgsl: emits nothing.
        return patch_discarded();
    }
    let normal = source_vec3(source + 21u);  // the unit normal: record 1, as border_compute reads it
    let rgba = vec4f(patch_source[source + 40u], patch_source[source + 41u],
                     patch_source[source + 42u], patch_source[source + 43u]);
    var point = base;
    var uv = vec2f(0.0, 1.0);  // inside for every fan corner
    var is_patch = 0u;
    if (corner == 1u) { point = p0; }
    else if (corner == 2u) { point = p2; }
    else if (corner == 3u) { point = p0; uv = vec2f(0.0, 0.0); is_patch = 1u; }
    else if (corner == 4u) { point = p1; uv = vec2f(0.5, 0.0); is_patch = 1u; }
    else if (corner == 5u) { point = p2; uv = vec2f(1.0, 1.0); is_patch = 1u; }
    var out: PatchOut;
    out.point = point;
    out.normal = normal;
    out.color = finalize_color(rgba, point, normal);
    out.v_clip = compute_clip_distance(point);
    out.curve_uv = uv;
    out.is_patch = is_patch;
    out.position = emit_gl_position(point);
    return out;
}

fn patch_outside(vin: PatchOut) -> bool {
    if (vin.v_clip < 0.0) { return true; }
    return vin.is_patch == 1u && vin.curve_uv.y - vin.curve_uv.x * vin.curve_uv.x < 0.0;
}

@fragment
fn fs_mark(vin: PatchOut) {
    if (patch_outside(vin)) { discard; }
}

@fragment
fn fs_surface(vin: PatchOut) -> @location(0) vec4f {
    if (patch_outside(vin)) { discard; }
    return output_color(vin.color);
}

@fragment
fn fs_paint(vin: PatchOut) -> @location(0) vec4f {
    if (patch_outside(vin)) { discard; }
    return output_color(finalize_color(source_paint(vin.point), vin.point, normalize(vin.normal)));
}
