// Browser-only: present the offscreen rgba8unorm scene target on the
// canvas (whose swapchain format is platform-preferred, e.g.
// bgra8unorm on macOS). Plain copy, no blending.

@group(0) @binding(0) var scene_texture: texture_2d<f32>;
@group(0) @binding(1) var scene_sampler: sampler;

struct BlitOut {
    @builtin(position) position: vec4f,
    @location(0) uv: vec2f,
}

@vertex
fn vs_main(@builtin(vertex_index) vid: u32) -> BlitOut {
    // Fullscreen triangle
    var out: BlitOut;
    let x = f32(i32(vid) / 2) * 4.0 - 1.0;
    let y = f32(i32(vid) % 2) * 4.0 - 1.0;
    out.position = vec4f(x, y, 0.0, 1.0);
    out.uv = vec2f((x + 1.0) * 0.5, 1.0 - (y + 1.0) * 0.5);
    return out;
}

@fragment
fn fs_main(vin: BlitOut) -> @location(0) vec4f {
    return textureSample(scene_texture, scene_sampler, vin.uv);
}
