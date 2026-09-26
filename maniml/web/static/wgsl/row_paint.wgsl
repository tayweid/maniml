// The paint program (docs/phase_b3_plan.md): a VMobject's rows with every
// row's stroke opacity and fill opacity set (VFadeIn, VFadeOut), as
// set_stroke(opacity=) and set_fill(opacity=) write them.
struct PaintParams {
    rows: u32,
    stroke_opacity: f32,
    fill_opacity: f32,
    reserved0: u32,
}
@group(0) @binding(0) var<uniform> paint_params: PaintParams;
@group(1) @binding(0) var<storage, read> paint_in: array<f32>;
@group(1) @binding(1) var<storage, read_write> paint_out: array<f32>;

@compute @workgroup_size(64)
fn cs_main(@builtin(global_invocation_id) id: vec3u) {
    let row = id.x;
    if (row >= paint_params.rows) { return; }
    let base = row * 17u;
    for (var j = 0u; j < 17u; j += 1u) {
        paint_out[base + j] = paint_in[base + j];
    }
    paint_out[base + 6u] = paint_params.stroke_opacity;
    paint_out[base + 12u] = paint_params.fill_opacity;
}
