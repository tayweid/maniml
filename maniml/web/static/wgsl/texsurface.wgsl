// TexturedSurface with the day/night light blend.

@group(1) @binding(0) var light_texture: texture_2d<f32>;
@group(1) @binding(1) var dark_texture: texture_2d<f32>;
@group(1) @binding(2) var surface_sampler: sampler;

struct TexSurfaceIn {
    @location(0) point: vec3f,
    @location(1) d_normal_point: vec3f,
    @location(2) im_coords: vec2f,
    @location(3) opacity: f32,
}

struct TexSurfaceOut {
    @builtin(position) position: vec4f,
    @location(0) point: vec3f,
    @location(1) unit_normal: vec3f,
    @location(2) uv: vec2f,
    @location(3) opacity: f32,
    @location(4) v_clip: f32,
}

const dark_shift: f32 = 0.2;

@vertex
fn vs_main(vin: TexSurfaceIn) -> TexSurfaceOut {
    var out: TexSurfaceOut;
    out.point = vin.point;
    out.unit_normal = normalize(vin.d_normal_point - vin.point);
    out.uv = vin.im_coords;
    out.opacity = vin.opacity;
    out.v_clip = compute_clip_distance(vin.point);
    out.position = emit_gl_position(vin.point);
    return out;
}

@fragment
fn fs_main(vin: TexSurfaceOut) -> @location(0) vec4f {
    if (vin.v_clip < 0.0) { discard; }
    var color = textureSample(light_texture, surface_sampler, vin.uv);
    let dark_color = textureSample(dark_texture, surface_sampler, vin.uv);
    if (u.num_textures == 2.0) {
        let dp = dot(
            normalize(u.light_position - vin.point),
            vin.unit_normal
        );
        let alpha = smoothstep(-dark_shift, dark_shift, dp);
        color = mix(dark_color, color, alpha);
    }
    if (color.a == 0.0) { discard; }

    var frag = finalize_color(color, vin.point, vin.unit_normal);
    frag.a = vin.opacity;
    return frag;
}
