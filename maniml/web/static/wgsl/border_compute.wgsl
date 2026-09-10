// Hardened hard-coverage border emitter; compile after common.wgsl.
// Input: 44 f32/curve = three 48-byte BorderSource records, density,
// active, density_capped flag, one reserved float, then actual source RGBA.
// Output: vertices_per_curve Surface vertices/curve (even, 4..64), ten
// tightly packed floats/vertex. The strip pattern the drivers build for
// that capacity clamps unused sample pairs to a degenerate tail.
struct BorderParams {
    curve_offset: u32,
    curve_count: u32,
    output_vertex_base: u32,
    normal_offset: f32,
    vertices_per_curve: u32,
    reserved0: u32,
    reserved1: u32,
    reserved2: u32,
}
@group(0) @binding(1) var<uniform> border_params: BorderParams;
@group(1) @binding(0) var<storage, read> border_source: array<f32>;
@group(1) @binding(1) var<storage, read_write> border_output: array<f32>;

fn border_vec3(index: u32) -> vec3f {
    return vec3f(border_source[index], border_source[index + 1u], border_source[index + 2u]);
}

fn border_unit(value: vec3f) -> vec3f {
    // Scaling also avoids overflow/underflow in length() for finite vectors.
    let magnitude = max(max(abs(value.x), abs(value.y)), abs(value.z));
    if (magnitude == 0.0) { return vec3f(0.0); }
    let scaled = value / magnitude;
    return scaled / length(scaled);
}

fn border_unit_or(value: vec3f, fallback: vec3f) -> vec3f {
    if (any(value != vec3f(0.0))) { return border_unit(value); }
    return border_unit(fallback);
}

fn border_project(value: vec3f, normal: vec3f) -> vec3f {
    return value - dot(value, normal) * normal;
}

fn border_smooth(left: f32, right: f32, value: f32) -> f32 {
    // Keep the same explicit polynomial used by the CPU reference.
    let t = clamp((value - left) / (right - left), 0.0, 1.0);
    return t * t * (3.0 - 2.0 * t);
}

fn border_write(vertex: u32, point: vec3f, normal: vec3f, rgba: vec4f) {
    let offset = 10u * vertex;
    let normal_point = point + 0.001 * normal;
    border_output[offset] = point.x;
    border_output[offset + 1u] = point.y;
    border_output[offset + 2u] = point.z;
    border_output[offset + 3u] = normal_point.x;
    border_output[offset + 4u] = normal_point.y;
    border_output[offset + 5u] = normal_point.z;
    border_output[offset + 6u] = rgba.x;
    border_output[offset + 7u] = rgba.y;
    border_output[offset + 8u] = rgba.z;
    border_output[offset + 9u] = rgba.w;
}

@compute @workgroup_size(64)
fn cs_main(@builtin(workgroup_id) group: vec3u,
           @builtin(local_invocation_index) vertex: u32) {
    let capacity = border_params.vertices_per_curve;
    if (group.x >= border_params.curve_count || vertex >= capacity) { return; }
    let source = 44u * (border_params.curve_offset + group.x);
    let output = border_params.output_vertex_base + capacity * group.x + vertex;
    let p0 = border_vec3(source);
    let p1 = border_vec3(source + 12u);
    let p2 = border_vec3(source + 24u);
    let source_normal = border_vec3(source + 21u);
    let rgba = vec4f(border_source[source + 40u], border_source[source + 41u],
                     border_source[source + 42u], border_source[source + 43u]);
    if (border_source[source + 37u] == 0.0) {
        // A single repeated position gives zero-area triangles for every index.
        border_write(output, p0, source_normal, rgba);
        return;
    }
    // The old float32 area estimate can overflow for finite source points.
    // Its +infinity density always selects32 steps, even at very large zoom
    // scales. An explicit flag preserves that policy without storing infinity.
    // The sender reserves capacity from the steps its curves need, so the
    // capacity bound below only guards a stale reservation.
    let most = min(32u, capacity / 2u);
    var count = most;
    if (border_source[source + 38u] == 0.0) {
        count = u32(clamp(2.0 + round(border_source[source + 36u] / u.frame_scale), 2.0, f32(most)));
    }
    let last = count - 1u;
    let step = min(vertex / 2u, last);
    let t = f32(step) / f32(last);
    let c1 = 2.0 * (p1 - p0);
    let c2 = p0 - 2.0 * p1 + p2;
    let position = p0 + c1 * t + c2 * t * t;
    var tangent = c1 + 2.0 * c2 * t;
    if (all(tangent == vec3f(0.0))) {
        let chord = p2 - p0;
        tangent = select(c1, chord, any(chord != vec3f(0.0)));
    }
    let flat = u.flat_stroke != 0.0 || u.is_fixed_in_frame != 0.0;
    var normal = source_normal;
    if (!flat) { normal = border_unit_or(u.camera_position - position, source_normal); }
    var projected_tangent = tangent;
    if (!flat) { projected_tangent = border_project(tangent, normal); }
    let unit_tangent = border_unit(projected_tangent);
    let fallback = cross(source_normal, tangent);
    var direction = border_unit_or(cross(normal, unit_tangent), fallback);
    var angle = 0.0;
    if (step == 0u) { angle = -border_source[source + 8u]; }
    else if (step == last) { angle = border_source[source + 32u]; }
    let alignment = abs(dot(border_unit(tangent), normal));
    if (angle != 0.0 && alignment > 0.97) {
        let perpendicular = border_unit(fallback);
        direction = mix(direction, border_project(direction, perpendicular),
                        border_smooth(0.97, 1.0, alignment));
    }
    let joint = i32(u.joint_type);
    if (joint != 0 && (step == 0u || step == last)) {
        var cosine = cos(angle);
        var sine = sin(angle);
        if (abs(cosine) <= 0.999) {
            var valid_corner = true;
            if (!flat) {
                direction = border_unit_or(cross(normal, unit_tangent), fallback);
                let adjacent = border_project(cosine * tangent + sine * fallback, normal);
                cosine = clamp(dot(unit_tangent, border_unit(adjacent)), -1.0, 1.0);
                sine = sqrt(max(0.0, 1.0 - cosine * cosine)) * sign(angle)
                       * sign(dot(normal, source_normal));
                valid_corner = abs(sine) >= 1e-12;
            }
            if (valid_corner) {
                var miter = border_smooth(-0.8, -0.9, cosine);
                if (joint == 2) { miter = 0.0; }
                else if (joint == 3) { miter = 1.0; }
                direction += ((cosine - 1.0 + 2.0 * miter) / sine) * unit_tangent;
            }
        }
    }
    let width_factor = 0.01 * (u.frame_scale * (1.0 - u.scale_stroke_with_zoom)
                              + u.scale_stroke_with_zoom);
    let half_width = 0.5 * width_factor * ((1.0 - t) * border_source[source + 7u]
                                        + t * border_source[source + 31u]);
    let side = select(-1.0, 1.0, vertex % 2u == 1u);
    let point = position + border_params.normal_offset * normal + side * half_width * direction;
    border_write(output, point, normal, rgba);
}
