// DotCloud billboard quads, one instance per dot, 4 vertices.

struct DotIn {
    @location(0) dot_point: vec3f,
    @location(1) dot_radius: f32,
    @location(2) dot_rgba: vec4f,
}

struct DotOut {
    @builtin(position) position: vec4f,
    @location(0) color: vec4f,
    @location(1) scaled_aaw: f32,
    @location(2) point: vec3f,
    @location(3) to_cam: vec3f,
    @location(4) center: vec3f,
    @location(5) radius: f32,
    @location(6) uv_coords: vec2f,
    @location(7) v_clip: f32,
}

@vertex
fn vs_main(vin: DotIn, @builtin(vertex_index) vid: u32) -> DotOut {
    var out: DotOut;
    out.color = vin.dot_rgba;
    out.radius = vin.dot_radius;
    out.center = vin.dot_point;
    out.scaled_aaw = (u.anti_alias_width * u.pixel_size) / vin.dot_radius;

    out.to_cam = normalize(u.camera_position - vin.dot_point);
    let right = vin.dot_radius
        * normalize(cross(vec3f(0.0, 1.0, 1.0), out.to_cam));
    let up = vin.dot_radius * normalize(cross(out.to_cam, right));

    // Geometry shader's loop order: i=-1 (j=-1, j=+1), i=+1 (j=-1, j=+1)
    var fi = 1.0;
    if (vid < 2u) { fi = -1.0; }
    var fj = 1.0;
    if (vid % 2u == 0u) { fj = -1.0; }

    out.point = vin.dot_point + fi * right + fj * up;
    out.uv_coords = vec2f(fi, fj);
    out.v_clip = compute_clip_distance(out.point);
    out.position = emit_gl_position(out.point);
    return out;
}

@fragment
fn fs_main(vin: DotOut) -> @location(0) vec4f {
    if (vin.v_clip < 0.0) { discard; }
    let r = length(vin.uv_coords.xy);
    if (r > 1.0) { discard; }

    var frag = vin.color;

    if (u.glow_factor > 0.0) {
        frag.a = frag.a * pow(1.0 - r, u.glow_factor);
    }

    if (any(u.shading != vec3f(0.0))) {
        let point_3d = vin.point
            + vin.radius * sqrt(1.0 - r * r) * vin.to_cam;
        let normal = normalize(point_3d - vin.center);
        frag = finalize_color(frag, point_3d, normal);
    }

    frag.a = frag.a * smoothstep(1.0, 1.0 - vin.scaled_aaw, r);
    return frag;
}
