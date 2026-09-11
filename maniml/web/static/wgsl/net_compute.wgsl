// Evaluates a biquadratic Bézier net at screen density (docs/phase_b2_plan.md);
// compile after common.wgsl.
//
// Input: one object's control net, `channels` f32 per control point in the
// vertex layout the surface draws (point, normal point, RGBA for a surface;
// point, normal point, image coordinates, opacity for a textured one), row
// major over (nu, nv). Output: per patch, (capacity + 1)² vertices of the
// same channels, on a grid of `steps ≤ capacity` per edge; the rows and
// columns beyond `steps` repeat the last one, so the index pattern the
// drivers build for the capacity draws zero-area triangles there. Steps
// follow the object's second difference at the current zoom: a quadratic's
// chord deviation over one step is a quarter of its second difference over
// steps², and the target is a quarter of an output pixel.
struct NetParams {
    net_offset: u32,          // first f32 of the object's net in net_source
    nu: u32,                  // control points along u (odd)
    nv: u32,                  // control points along v (odd)
    channels: u32,            // f32 per control point and per output vertex
    capacity: u32,            // reserved steps per patch edge
    output_vertex_base: u32,  // first output vertex of patch 0
    patch_offset: u32,        // first patch of this dispatch
    patch_count: u32,
    density: f32,             // the largest second difference, world units
    pixels_per_unit: f32,     // output pixels per world unit at frame scale 1
    reserved0: f32,
    reserved1: f32,
}
@group(0) @binding(1) var<uniform> net_params: NetParams;
@group(1) @binding(0) var<storage, read> net_source: array<f32>;
@group(1) @binding(1) var<storage, read_write> net_output: array<f32>;

fn bernstein(t: f32) -> vec3f {
    return vec3f((1.0 - t) * (1.0 - t), 2.0 * t * (1.0 - t), t * t);
}

@compute @workgroup_size(64)
fn cs_main(@builtin(workgroup_id) group: vec3u, @builtin(local_invocation_index) local: u32) {
    let patch_id = group.x;
    if (patch_id >= net_params.patch_count) { return; }
    let capacity = net_params.capacity;
    let side = capacity + 1u;
    let vertex = group.y * 64u + local;
    if (vertex >= side * side) { return; }
    // Steps at this zoom: the deviation over one step must stay under a
    // quarter pixel, and never fewer than two, the construction's own
    // samples, since lighting is per vertex and fewer vertices than the
    // samples would shade more coarsely than the CPU grid. frame_scale
    // scales the frame, so pixels per unit fall with it; a capped
    // reservation only guards a stale one.
    let pixels = net_params.density * net_params.pixels_per_unit / u.frame_scale;
    var steps = 2u;
    if (pixels > 4.0) {
        steps = u32(ceil(sqrt(pixels)));
    }
    steps = min(steps, capacity);
    let index = net_params.patch_offset + patch_id;
    let patches_v = (net_params.nv - 1u) / 2u;
    let i = index / patches_v;
    let j = index % patches_v;
    let a = min(vertex / side, steps);
    let b = min(vertex % side, steps);
    let wu = bernstein(f32(a) / f32(steps));
    let wv = bernstein(f32(b) / f32(steps));
    let channels = net_params.channels;
    let out = (net_params.output_vertex_base + patch_id * side * side + vertex) * channels;
    for (var c = 0u; c < channels; c += 1u) {
        var value = 0.0;
        for (var r = 0u; r < 3u; r += 1u) {
            for (var s = 0u; s < 3u; s += 1u) {
                let control = net_params.net_offset + ((2u * i + r) * net_params.nv + (2u * j + s)) * channels + c;
                value += wu[r] * wv[s] * net_source[control];
            }
        }
        net_output[out + c] = value;
    }
}
