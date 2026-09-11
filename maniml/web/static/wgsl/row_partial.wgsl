// The partial program (docs/phase_b3_plan.md): the part of a path between
// two proportions, as VMobject.pointwise_become_partial writes it
// (ShowCreation, Uncreate, the border phase of DrawBorderThenFill). The
// curve indices and residues come from the CPU, computed as it computes
// them; only the Bézier arithmetic is float32 here. Rows before the lower
// curve collapse onto its start, rows from the upper curve's end on
// collapse onto that end, and their joint angles are zero.
struct PartialParams {
    rows: u32,
    curves: u32,
    lower: u32,
    upper: u32,
    lower_residue: f32,
    upper_residue: f32,
    full: u32,       // a <= 0 and b >= 1: the rows are the source's
    reserved0: u32,
}
@group(0) @binding(0) var<uniform> partial_params: PartialParams;
@group(1) @binding(0) var<storage, read> partial_in: array<f32>;
@group(1) @binding(1) var<storage, read_write> partial_out: array<f32>;

fn point_at(row: u32) -> vec3f {
    let base = row * 17u;
    return vec3f(partial_in[base], partial_in[base + 1u], partial_in[base + 2u]);
}

fn curve_at(p0: vec3f, p1: vec3f, p2: vec3f, t: f32) -> vec3f {
    return p0 * (1.0 - t) * (1.0 - t) + 2.0 * p1 * t * (1.0 - t) + p2 * t * t;
}

// partial_quadratic_bezier_points(points, a, b)[k]
fn partial_point(first: u32, a: f32, b: f32, k: u32) -> vec3f {
    let p0 = point_at(first);
    let p1 = point_at(first + 1u);
    let p2 = point_at(first + 2u);
    if (a == 1.0) { return p2; }
    var h0 = p0;
    if (a > 0.0) { h0 = curve_at(p0, p1, p2, a); }
    var h2 = p2;
    if (b < 1.0) { h2 = curve_at(p0, p1, p2, b); }
    let h1_prime = (1.0 - a) * p1 + a * p2;
    let end_prop = (b - a) / (1.0 - a);
    let h1 = (1.0 - end_prop) * h0 + end_prop * h1_prime;
    if (k == 0u) { return h0; }
    if (k == 1u) { return h1; }
    return h2;
}

@compute @workgroup_size(64)
fn cs_main(@builtin(global_invocation_id) id: vec3u) {
    let row = id.x;
    if (row >= partial_params.rows) { return; }
    let base = row * 17u;
    for (var j = 0u; j < 17u; j += 1u) {
        partial_out[base + j] = partial_in[base + j];
    }
    if (partial_params.full != 0u || partial_params.curves == 0u) { return; }
    let i1 = 2u * partial_params.lower;
    let i2 = i1 + 3u;
    let i3 = 2u * partial_params.upper;
    let i4 = i3 + 3u;
    let lower_residue = partial_params.lower_residue;
    let upper_residue = partial_params.upper_residue;
    var point = point_at(row);
    if (partial_params.lower == partial_params.upper) {
        if (row < i1) {
            point = partial_point(i1, lower_residue, upper_residue, 0u);
        } else if (row < i4) {
            point = partial_point(i1, lower_residue, upper_residue, row - i1);
        } else {
            point = partial_point(i1, lower_residue, upper_residue, 2u);
        }
    } else {
        if (row < i1) {
            point = partial_point(i1, lower_residue, 1.0, 0u);
        } else if (row < i2) {
            point = partial_point(i1, lower_residue, 1.0, row - i1);
        } else if (row < i3) {
            // kept as it is
        } else if (row < i4) {
            point = partial_point(i3, 0.0, upper_residue, row - i3);
        } else {
            point = partial_point(i3, 0.0, upper_residue, 2u);
        }
    }
    partial_out[base] = point.x;
    partial_out[base + 1u] = point.y;
    partial_out[base + 2u] = point.z;
    if (row < i1 || row >= i4) {
        partial_out[base + 8u] = 0.0;
    }
    if (row % 2u == 0u) {
        // The base point rows: the path's new first point, which is the
        // lower curve's cut start (h0 does not depend on the upper bound).
        let first = partial_point(i1, lower_residue, 1.0, 0u);
        partial_out[base + 13u] = first.x;
        partial_out[base + 14u] = first.y;
        partial_out[base + 15u] = first.z;
    }
}
