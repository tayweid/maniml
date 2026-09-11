// Finalize evaluated VMobject rows (docs/phase_b3_plan.md) into what the
// drawing stages consume: the 44-word curve records the border compute and
// patch fill read (gpu_border_geometry.pack_source's layout), and the
// 68-byte stroke instances the stroke pipeline reads (three consecutive
// rows per curve, verbatim). Curve i is rows 2i, 2i+1, 2i+2, the pattern
// VMobject.get_outer_vert_indices builds.
//
// A row is seventeen floats: point 0..2, stroke_rgba 3..6, stroke_width 7,
// joint_angle 8, fill_rgba 9..12, base_normal 13..15 (a base point on even
// rows, the unit normal on odd rows), fill_border_width 16.
struct FinalizeParams {
    curves: u32,
    row_floats: u32,   // 17
    reserved0: u32,
    reserved1: u32,
}
@group(0) @binding(0) var<uniform> finalize_params: FinalizeParams;
@group(1) @binding(0) var<storage, read> rows: array<f32>;
@group(1) @binding(1) var<storage, read_write> records: array<f32>;  // 44 per curve
@group(1) @binding(2) var<storage, read_write> strokes: array<f32>;  // 51 per curve

fn row_vec3(base: u32, offset: u32) -> vec3f {
    return vec3f(rows[base + offset], rows[base + offset + 1u], rows[base + offset + 2u]);
}

@compute @workgroup_size(64)
fn cs_main(@builtin(global_invocation_id) id: vec3u) {
    let curve = id.x;
    if (curve >= finalize_params.curves) { return; }
    let stride = finalize_params.row_floats;
    let record = 44u * curve;
    let instance = 51u * curve;
    var fill_alpha = 0.0;
    var width = 0.0;
    for (var k = 0u; k < 3u; k += 1u) {
        let base = (2u * curve + k) * stride;
        for (var j = 0u; j < 17u; j += 1u) {
            strokes[instance + 17u * k + j] = rows[base + j];
        }
        let slot = record + 12u * k;
        records[slot] = rows[base];
        records[slot + 1u] = rows[base + 1u];
        records[slot + 2u] = rows[base + 2u];
        records[slot + 7u] = rows[base + 16u];  // fill border width
        records[slot + 8u] = rows[base + 8u];   // joint angle
        records[slot + 9u] = rows[base + 13u];  // base point or unit normal
        records[slot + 10u] = rows[base + 14u];
        records[slot + 11u] = rows[base + 15u];
        fill_alpha = max(fill_alpha, abs(rows[base + 12u]));
        width = max(width, abs(rows[base + 16u]));
    }
    let p0 = row_vec3(2u * curve * stride, 0u);
    let p1 = row_vec3((2u * curve + 1u) * stride, 0u);
    let p2 = row_vec3((2u * curve + 2u) * stride, 0u);
    // The border stage's density, float32 as the CPU computes it; an
    // overflow becomes the capped flag rather than a nonfinite word.
    let area = 0.5 * length(cross(p1 - p0, p2 - p0));
    var density = 100.0 * sqrt(area);
    let capped = density != density || density > 3.0e38;
    if (capped) { density = 0.0; }
    let is_active = fill_alpha != 0.0 && any(p0 != p1) && width != 0.0;
    for (var k = 0u; k < 3u; k += 1u) {
        let slot = record + 12u * k;
        records[slot + 3u] = 1.0;
        records[slot + 4u] = 1.0;
        records[slot + 5u] = 1.0;
        records[slot + 6u] = select(0.0, 1.0, is_active);
    }
    records[record + 36u] = density;
    records[record + 37u] = select(0.0, 1.0, is_active);
    records[record + 38u] = select(0.0, 1.0, capped);
    records[record + 39u] = 0.0;
    // The object's colour: the first row's fill, as pack_source takes it.
    records[record + 40u] = rows[9u];
    records[record + 41u] = rows[10u];
    records[record + 42u] = rows[11u];
    records[record + 43u] = rows[12u];
}
