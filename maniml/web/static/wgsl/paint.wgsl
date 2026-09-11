// Source-space vector paint and lighting, independent of fill triangulation.
// Storage layout is defined by web/fill_paint.py: six header vec4s, then pairs
// of sample coordinates and coefficients. Vertex format is Surface's 40 bytes.
@group(1) @binding(0) var<storage, read> paint: array<vec4f>;

struct PaintIn {
    @location(0) point: vec3f,
    @location(1) d_normal_point: vec3f,
    @location(2) rgba: vec4f,
}
struct PaintOut {
    @builtin(position) position: vec4f,
    @location(0) point: vec3f,
    @location(1) normal: vec3f,
    @location(2) v_clip: f32,
}

@vertex
fn vs_main(vin: PaintIn) -> PaintOut {
    var out: PaintOut;
    out.position = emit_gl_position(vin.point);
    out.point = vin.point;
    out.normal = vin.d_normal_point - vin.point;
    out.v_clip = compute_clip_distance(vin.point);
    return out;
}

@fragment
fn fs_main(vin: PaintOut) -> @location(0) vec4f {
    if (vin.v_clip < 0.0) { discard; }
    return output_color(finalize_color(source_paint(vin.point), vin.point, normalize(vin.normal)));
}
