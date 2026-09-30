// Finalize a frame's row sources in one dispatch (docs/phase_b4_plan.md,
// B5.8): every path whose output moved, in a table, each one's curve
// records (a patch run's member) or stroke instances (a stroke's) written
// into rows_output at its offset, which the driver copies into the output
// its batch owns. The arithmetic is row_finalize.wgsl's, word for word
// (a program's rows are still finalized there, one pass a program), and
// tests hold the two kernels to the same words.
//
// A path travels as its geometry, nine float32 columns a row (point 0..2,
// stroke width 3, joint angle 4, base point on even rows and unit normal on
// odd rows 5..7, fill border width 8), keyed on them alone, and its paint,
// eight a row (stroke RGBA 0..3, fill RGBA 4..7), one row for the whole
// path where every row has the same (read at paint stride 0). A recording
// made before B5.8 names seventeen-column rows whose paint is their own
// (flags bit 1): VMobject's row, point 0..2, stroke_rgba 3..6,
// stroke_width 7, joint_angle 8, fill_rgba 9..12, base_normal 13..15,
// fill_border_width 16.
//
// The table and the inputs share one binding: after the four header
// words, eight words an entry, then the inputs the entries point into.
//   geometry      first word of the path's geometry (or legacy rows)
//   paint         first word of its paint
//   paint_stride  words from one row's paint to the next's: 8, or 0
//   output        first f32 of its outputs in rows_output
//   curves        its curves, (rows - 1) / 2
//   flags         bit 0: stroke instances (51 words a curve), else curve
//                 records (44); bit 1: legacy seventeen-column rows
//   curve_start   the dispatch's first curve of this entry
struct RowTableParams {
    count: u32,     // entries
    curves: u32,    // curves over every entry: one invocation each
    reserved0: u32,
    reserved1: u32,
    words: array<u32>,
}
@group(0) @binding(0) var<storage, read> row_table: RowTableParams;
@group(1) @binding(0) var<storage, read_write> rows_output: array<f32>;

fn input_word(index: u32) -> f32 {
    return bitcast<f32>(row_table.words[index]);
}

@compute @workgroup_size(64)
fn cs_main(@builtin(workgroup_id) group: vec3u, @builtin(num_workgroups) groups: vec3u,
           @builtin(local_invocation_index) local: u32) {
    let work = (group.y * groups.x + group.x) * 64u + local;
    if (work >= row_table.curves) { return; }
    // The entry that holds this curve: the last whose first curve is not past it.
    var low = 0u;
    var high = row_table.count;
    while (high - low > 1u) {
        let middle = (low + high) / 2u;
        if (row_table.words[8u * middle + 6u] <= work) { low = middle; } else { high = middle; }
    }
    let entry = 8u * low;
    let geometry = row_table.words[entry];
    let paint = row_table.words[entry + 1u];
    let paint_stride = row_table.words[entry + 2u];
    let output = row_table.words[entry + 3u];
    let flags = row_table.words[entry + 5u];
    let curve = work - row_table.words[entry + 6u];
    let legacy = (flags & 2u) != 0u;
    // The curve's three rows, 2i, 2i+1 and 2i+2, in VMobject's columns.
    var r: array<f32, 51>;
    for (var k = 0u; k < 3u; k += 1u) {
        let row = 2u * curve + k;
        let at = 17u * k;
        if (legacy) {
            let base = geometry + 17u * row;
            for (var j = 0u; j < 17u; j += 1u) {
                r[at + j] = input_word(base + j);
            }
        } else {
            let g = geometry + 9u * row;
            let p = paint + paint_stride * row;
            r[at] = input_word(g);
            r[at + 1u] = input_word(g + 1u);
            r[at + 2u] = input_word(g + 2u);
            for (var j = 0u; j < 4u; j += 1u) {
                r[at + 3u + j] = input_word(p + j);        // stroke RGBA
                r[at + 9u + j] = input_word(p + 4u + j);   // fill RGBA
            }
            r[at + 7u] = input_word(g + 3u);   // stroke width
            r[at + 8u] = input_word(g + 4u);   // joint angle
            r[at + 13u] = input_word(g + 5u);  // base point or unit normal
            r[at + 14u] = input_word(g + 6u);
            r[at + 15u] = input_word(g + 7u);
            r[at + 16u] = input_word(g + 8u);  // fill border width
        }
    }
    if ((flags & 1u) != 0u) {
        // Stroke instances: the three rows verbatim.
        let instance = output + 51u * curve;
        for (var j = 0u; j < 51u; j += 1u) {
            rows_output[instance + j] = r[j];
        }
        return;
    }
    let record = output + 44u * curve;
    var fill_alpha = 0.0;
    var width = 0.0;
    for (var k = 0u; k < 3u; k += 1u) {
        let at = 17u * k;
        let slot = record + 12u * k;
        rows_output[slot] = r[at];
        rows_output[slot + 1u] = r[at + 1u];
        rows_output[slot + 2u] = r[at + 2u];
        rows_output[slot + 7u] = r[at + 16u];  // fill border width
        rows_output[slot + 8u] = r[at + 8u];   // joint angle
        rows_output[slot + 9u] = r[at + 13u];  // base point or unit normal
        rows_output[slot + 10u] = r[at + 14u];
        rows_output[slot + 11u] = r[at + 15u];
        fill_alpha = max(fill_alpha, abs(r[at + 12u]));
        width = max(width, abs(r[at + 16u]));
    }
    let p0 = vec3f(r[0], r[1], r[2]);
    let p1 = vec3f(r[17], r[18], r[19]);
    let p2 = vec3f(r[34], r[35], r[36]);
    // The border stage's density, float32 as the CPU computes it; an
    // overflow becomes the capped flag rather than a nonfinite word.
    let area = 0.5 * length(cross(p1 - p0, p2 - p0));
    var density = 100.0 * sqrt(area);
    let capped = density != density || density > 3.0e38;
    if (capped) { density = 0.0; }
    let is_active = fill_alpha != 0.0 && any(p0 != p1) && width != 0.0;
    for (var k = 0u; k < 3u; k += 1u) {
        let slot = record + 12u * k;
        rows_output[slot + 3u] = 1.0;
        rows_output[slot + 4u] = 1.0;
        rows_output[slot + 5u] = 1.0;
        rows_output[slot + 6u] = select(0.0, 1.0, is_active);
    }
    rows_output[record + 36u] = density;
    rows_output[record + 37u] = select(0.0, 1.0, is_active);
    rows_output[record + 38u] = select(0.0, 1.0, capped);
    rows_output[record + 39u] = 0.0;
    // The object's colour: its first row's fill, as pack_source takes it.
    var first = paint + 4u;
    if (legacy) { first = geometry + 9u; }
    rows_output[record + 40u] = input_word(first);
    rows_output[record + 41u] = input_word(first + 1u);
    rows_output[record + 42u] = input_word(first + 2u);
    rows_output[record + 43u] = input_word(first + 3u);
}
