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

fn source_paint(point: vec3f) -> vec4f {
    let local = (point - paint[0].xyz) / paint[0].w;
    let xy = vec2f(dot(local, paint[1].xyz), dot(local, paint[2].xyz));
    let count = u32(paint[1].w);
    let positive = paint[2].w != 0.0;
    var result = paint[3] + xy.x * paint[4] + xy.y * paint[5];
    var total = 0.0;
    if (positive) { result = vec4f(0.0); }
    for (var i = 0u; i < count; i += 1u) {
        let delta = xy - paint[6u + 2u * i].xy;
        let squared = dot(delta, delta);
        var weight = 0.5 * squared * log(max(squared, 1e-20));
        if (positive) { weight = 1.0 / max(squared, 1e-20); }
        result += weight * paint[7u + 2u * i];
        total += weight;
    }
    if (positive) { result /= total; }
    return clamp(result, vec4f(0.0), vec4f(1.0));
}

@fragment
fn fs_main(vin: PaintOut) -> @location(0) vec4f {
    if (vin.v_clip < 0.0) { discard; }
    return output_color(finalize_color(source_paint(vin.point), vin.point, normalize(vin.normal)));
}
