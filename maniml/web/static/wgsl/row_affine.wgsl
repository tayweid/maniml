// The affine program (docs/phase_b3_plan.md): a VMobject's rows with every
// point mapped through a 4x4 affine matrix (Rotating: the start's points
// rotated about a point), the unit normal on odd rows mapped as a
// direction, everything else copied. Rows are seventeen floats; see
// row_finalize.wgsl for the layout.
struct AffineParams {
    rows: u32,
    row_floats: u32,   // 17
    reserved0: u32,
    reserved1: u32,
    matrix: mat4x4<f32>,
}
@group(0) @binding(0) var<uniform> affine_params: AffineParams;
@group(1) @binding(0) var<storage, read> affine_in: array<f32>;
@group(1) @binding(1) var<storage, read_write> affine_out: array<f32>;

@compute @workgroup_size(64)
fn cs_main(@builtin(global_invocation_id) id: vec3u) {
    let row = id.x;
    if (row >= affine_params.rows) { return; }
    let base = row * affine_params.row_floats;
    for (var j = 0u; j < affine_params.row_floats; j += 1u) {
        affine_out[base + j] = affine_in[base + j];
    }
    let point = affine_params.matrix * vec4f(affine_in[base], affine_in[base + 1u], affine_in[base + 2u], 1.0);
    affine_out[base] = point.x;
    affine_out[base + 1u] = point.y;
    affine_out[base + 2u] = point.z;
    // Odd rows hold the unit normal, a direction; even rows the base
    // point, which moves with the points.
    let w = select(1.0, 0.0, row % 2u == 1u);
    let other = affine_params.matrix * vec4f(affine_in[base + 13u], affine_in[base + 14u], affine_in[base + 15u], w);
    affine_out[base + 13u] = other.x;
    affine_out[base + 14u] = other.y;
    affine_out[base + 15u] = other.z;
}
