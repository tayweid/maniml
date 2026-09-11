// The blend program (docs/phase_b3_plan.md): out = mix(a, b, alpha) over
// every float of two row-aligned sources. A VMobject's rows are seventeen
// floats per control point; a surface net's rows are its channels. The CPU
// lerps every column the same way, so this is the whole program.
struct BlendParams {
    count: u32,   // floats to blend
    alpha: f32,
    reserved0: u32,
    reserved1: u32,
}
@group(0) @binding(0) var<uniform> blend_params: BlendParams;
@group(1) @binding(0) var<storage, read> blend_a: array<f32>;
@group(1) @binding(1) var<storage, read> blend_b: array<f32>;
@group(1) @binding(2) var<storage, read_write> blend_out: array<f32>;

@compute @workgroup_size(256)
fn cs_main(@builtin(global_invocation_id) id: vec3u) {
    let i = id.x;
    if (i >= blend_params.count) { return; }
    blend_out[i] = mix(blend_a[i], blend_b[i], blend_params.alpha);
}
