// WGSL port of web/static/glsl/composite.{vert,frag} — stamps the
// accumulated winding-fill texture onto the scene target.

@group(0) @binding(0) var fill_texture: texture_2d<f32>;
@group(0) @binding(1) var fill_sampler: sampler;

struct QuadOut {
    @builtin(position) position: vec4f,
    @location(0) uv: vec2f,
}

@vertex
fn vs_main(@location(0) texcoord: vec2f) -> QuadOut {
    var out: QuadOut;
    // GL's quad spans NDC via (2t-1) with y-up; WebGPU framebuffer y is
    // top-down, so flip v to keep the fill texture upright
    out.position = vec4f(2.0 * texcoord.x - 1.0, 2.0 * texcoord.y - 1.0,
                         0.0, 1.0);
    out.uv = vec2f(texcoord.x, 1.0 - texcoord.y);
    return out;
}

@fragment
fn fs_main(vin: QuadOut) -> @location(0) vec4f {
    var color = textureSample(fill_texture, fill_sampler, vin.uv);
    if (color.a == 0.0) { discard; }
    if (color.a < 0.0) {
        color.a = -color.a / (1.0 - color.a);
        color = vec4f(color.rgb * (color.a - 1.0), color.a);
    }
    // Counteract scaling in fill frag
    return color * 1.06;
}
