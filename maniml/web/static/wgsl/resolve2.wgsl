// Exact box resolve of four spatial texels in premultiplied RGBA. Run after
// the hardware MSAA resolve; postpone straight-alpha conversion to file output.
@group(0) @binding(0) var source: texture_2d<f32>;

@vertex
fn vs_main(@builtin(vertex_index) index: u32) -> @builtin(position) vec4f {
    let xy = array<vec2f, 3>(vec2f(-1.0, -1.0), vec2f(3.0, -1.0), vec2f(-1.0, 3.0));
    return vec4f(xy[index], 0.0, 1.0);
}

@fragment
fn fs_main(@builtin(position) position: vec4f) -> @location(0) vec4f {
    let q = vec2i(position.xy) * 2;
    return 0.25 * (textureLoad(source, q, 0)
                  + textureLoad(source, q + vec2i(1, 0), 0)
                  + textureLoad(source, q + vec2i(0, 1), 0)
                  + textureLoad(source, q + vec2i(1, 1), 0));
}
