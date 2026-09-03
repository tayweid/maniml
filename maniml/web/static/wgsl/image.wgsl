// ImageMobject texture pipeline.

@group(1) @binding(0) var image_texture: texture_2d<f32>;
@group(1) @binding(1) var image_sampler: sampler;

struct ImageIn {
    @location(0) point: vec3f,
    @location(1) im_coords: vec2f,
    @location(2) opacity: f32,
}

struct ImageOut {
    @builtin(position) position: vec4f,
    @location(0) uv: vec2f,
    @location(1) opacity: f32,
    @location(2) v_clip: f32,
}

@vertex
fn vs_main(vin: ImageIn) -> ImageOut {
    var out: ImageOut;
    out.uv = vin.im_coords;
    out.opacity = vin.opacity;
    out.v_clip = compute_clip_distance(vin.point);
    out.position = emit_gl_position(vin.point);
    return out;
}

@fragment
fn fs_main(vin: ImageOut) -> @location(0) vec4f {
    if (vin.v_clip < 0.0) { discard; }
    var frag = textureSample(image_texture, image_sampler, vin.uv);
    frag.a = frag.a * vin.opacity;
    return frag;
}
