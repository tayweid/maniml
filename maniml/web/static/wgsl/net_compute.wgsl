// Evaluates biquadratic Bézier nets (docs/phase_b2_plan.md), every net a
// frame evaluates in one dispatch (docs/phase_b4_plan.md, B5.5).
//
// Input: the nets' control points in net_source, each net `channels` f32
// per control point in the vertex layout its surface draws (point, normal
// point, RGBA for a surface; point, normal point, image coordinates,
// opacity for a textured one), row major over (nu, nv). Output: per net and
// per patch, (capacity + 1)² vertices of the same channels in net_output,
// on a grid of `steps ≤ capacity` per edge; the rows and columns beyond
// `steps` repeat the last one, so the index pattern the drivers build for
// the capacity draws zero-area triangles there. The driver chooses the
// steps (the chord deviation of a quadratic over one step is a quarter of
// its second difference over steps², and the target is a quarter of an
// output pixel), so an output is a function of its control points, its
// capacity and its steps alone, and a camera move that changes none of
// them evaluates nothing. One workgroup evaluates one patch; the dispatch
// covers every patch of every entry, laid out in rows of num_workgroups.x.
struct NetEntry {
    source_offset: u32,  // first f32 of the net's control points in net_source
    output_offset: u32,  // first f32 of the net's vertices in net_output
    nu: u32,             // control points along u (odd)
    nv: u32,             // control points along v (odd)
    channels: u32,       // f32 per control point and per output vertex
    capacity: u32,       // reserved steps per patch edge
    steps: u32,          // steps per patch edge, 2 ≤ steps ≤ capacity
    patch_start: u32,    // the dispatch's first patch of this net
}
struct NetParams {
    count: u32,          // entries
    patches: u32,        // patches over every entry
    reserved0: u32,
    reserved1: u32,
    entries: array<NetEntry>,
}
@group(0) @binding(0) var<storage, read> net_params: NetParams;
@group(1) @binding(0) var<storage, read> net_source: array<f32>;
@group(1) @binding(1) var<storage, read_write> net_output: array<f32>;

fn bernstein(t: f32) -> vec3f {
    return vec3f((1.0 - t) * (1.0 - t), 2.0 * t * (1.0 - t), t * t);
}

@compute @workgroup_size(64)
fn cs_main(@builtin(workgroup_id) group: vec3u, @builtin(num_workgroups) groups: vec3u,
           @builtin(local_invocation_index) local: u32) {
    let work = group.y * groups.x + group.x;
    if (work >= net_params.patches) { return; }
    // The entry that holds this patch: the last whose first patch is not past it.
    var low = 0u;
    var high = net_params.count;
    while (high - low > 1u) {
        let middle = (low + high) / 2u;
        if (net_params.entries[middle].patch_start <= work) { low = middle; } else { high = middle; }
    }
    let net = net_params.entries[low];
    let patch_id = work - net.patch_start;
    let capacity = net.capacity;
    let side = capacity + 1u;
    let steps = clamp(net.steps, 2u, capacity);
    let patches_v = (net.nv - 1u) / 2u;
    let i = patch_id / patches_v;
    let j = patch_id % patches_v;
    let channels = net.channels;
    for (var vertex = local; vertex < side * side; vertex += 64u) {
        let a = min(vertex / side, steps);
        let b = min(vertex % side, steps);
        let wu = bernstein(f32(a) / f32(steps));
        let wv = bernstein(f32(b) / f32(steps));
        let out = net.output_offset + (patch_id * side * side + vertex) * channels;
        for (var c = 0u; c < channels; c += 1u) {
            var value = 0.0;
            for (var r = 0u; r < 3u; r += 1u) {
                for (var s = 0u; s < 3u; s += 1u) {
                    let control = net.source_offset + ((2u * i + r) * net.nv + (2u * j + s)) * channels + c;
                    value += wu[r] * wv[s] * net_source[control];
                }
            }
            net_output[out + c] = value;
        }
    }
}
