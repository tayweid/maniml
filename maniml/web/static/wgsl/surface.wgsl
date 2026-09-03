// Serves both the triangulated-fill path and Surface mobjects.

struct SurfaceIn {
    @location(0) point: vec3f,
    @location(1) d_normal_point: vec3f,
    @location(2) rgba: vec4f,
}

struct SurfaceOut {
    @builtin(position) position: vec4f,
    @location(0) color: vec4f,
    @location(1) v_clip: f32,
}

@vertex
fn vs_main(vin: SurfaceIn) -> SurfaceOut {
    var out: SurfaceOut;
    out.v_clip = compute_clip_distance(vin.point);
    out.position = emit_gl_position(vin.point);
    let unit_normal = normalize(vin.d_normal_point - vin.point);
    out.color = finalize_color(vin.rgba, vin.point, unit_normal);
    return out;
}

@fragment
fn fs_main(vin: SurfaceOut) -> @location(0) vec4f {
    if (vin.v_clip < 0.0) { discard; }
    return vin.color;
}
