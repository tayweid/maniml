// WGSL port of web/static/glsl/vstroke.{vert,frag} — the instanced
// adaptive-polyline stroke. Serves both the stroke pass and the
// fill-border pass (u.border_mode + different vertex buffer offsets).

struct StrokeIn {
    @location(0) p0: vec3f,
    @location(1) p1: vec3f,
    @location(2) p2: vec3f,
    @location(3) rgba0: vec4f,
    @location(4) rgba1: vec4f,
    @location(5) rgba2: vec4f,
    @location(6) width0: f32,
    @location(7) width1: f32,
    @location(8) width2: f32,
    @location(9) ja0: f32,
    @location(10) ja2: f32,
    @location(11) unit_normal1: vec3f,
}

struct StrokeOut {
    @builtin(position) position: vec4f,
    @location(0) color: vec4f,
    @location(1) dist_to_aaw: f32,
    @location(2) half_width_to_aaw: f32,
    @location(3) v_clip: f32,
}

const NO_JOINT: i32 = 0;
const BEVEL_JOINT: i32 = 2;
const MITER_JOINT: i32 = 3;
const COS_THRESHOLD: f32 = 0.999;
const POLYLINE_FACTOR: f32 = 100.0;
const MAX_STEPS: i32 = 32;
const MITER_COS_ANGLE_THRESHOLD: f32 = -0.8;
const STROKE_WIDTH_CONVERSION: f32 = 0.01;

fn point_on_quadratic(t: f32, c0: vec3f, c1: vec3f, c2: vec3f) -> vec3f {
    return c0 + c1 * t + c2 * t * t;
}

fn tangent_on_quadratic(t: f32, c1: vec3f, c2: vec3f) -> vec3f {
    return c1 + 2.0 * c2 * t;
}

fn project_onto_plane(vect: vec3f, unit_normal: vec3f) -> vec3f {
    return vect - dot(vect, unit_normal) * unit_normal;
}

fn rotate_vector(vect: vec3f, unit_normal: vec3f, angle: f32) -> vec3f {
    let perp = cross(unit_normal, vect);
    return cos(angle) * vect + sin(angle) * perp;
}

fn step_to_corner(
    point: vec3f, tangent: vec3f, unit_normal: vec3f, unit_normal1: vec3f,
    joint_angle: f32, inside_curve: bool, draw_flat: bool
) -> vec3f {
    var unit_tan: vec3f;
    if (draw_flat) {
        unit_tan = normalize(tangent);
    } else {
        unit_tan = normalize(project_onto_plane(tangent, unit_normal));
    }

    var step_dir = normalize(cross(unit_normal, unit_tan));

    if (joint_angle != 0.0) {
        let alignment = abs(dot(normalize(tangent), unit_normal));
        let alignment_threshold = 0.97;
        if (alignment > alignment_threshold) {
            let perp = normalize(cross(unit_normal1, tangent));
            step_dir = mix(
                step_dir,
                project_onto_plane(step_dir, perp),
                smoothstep(alignment_threshold, 1.0, alignment)
            );
        }
    }

    if (inside_curve || i32(u.joint_type) == NO_JOINT) {
        return step_dir;
    }

    var cos_angle = cos(joint_angle);
    var sin_angle = sin(joint_angle);

    if (abs(cos_angle) > COS_THRESHOLD) {
        return step_dir;
    }

    if (!draw_flat) {
        step_dir = normalize(cross(unit_normal, unit_tan));
        var adj_tan = rotate_vector(tangent, unit_normal1, joint_angle);
        adj_tan = project_onto_plane(adj_tan, unit_normal);
        cos_angle = dot(unit_tan, normalize(adj_tan));
        sin_angle = sqrt(1.0 - cos_angle * cos_angle) * sign(joint_angle)
            * sign(dot(unit_normal, unit_normal1));
    }

    var miter_factor: f32;
    let jt = i32(u.joint_type);
    if (jt == BEVEL_JOINT) {
        miter_factor = 0.0;
    } else if (jt == MITER_JOINT) {
        miter_factor = 1.0;
    } else {
        let mcat1 = MITER_COS_ANGLE_THRESHOLD;
        let mcat2 = mix(mcat1, -1.0, 0.5);
        miter_factor = smoothstep(mcat1, mcat2, cos_angle);
    }

    let shift = (cos_angle + mix(-1.0, 1.0, miter_factor)) / sin_angle;
    return step_dir + shift * unit_tan;
}

@vertex
fn vs_main(vin: StrokeIn, @builtin(vertex_index) vid: u32) -> StrokeOut {
    var out: StrokeOut;
    if (all(vin.p0 == vin.p1)
            || (vin.width0 == 0.0 && vin.width1 == 0.0 && vin.width2 == 0.0)
            || (vin.rgba0.a == 0.0 && vin.rgba1.a == 0.0
                && vin.rgba2.a == 0.0)) {
        out.position = DISCARD_POSITION;
        return out;
    }

    // The original vert stage's width conversion
    let width_factor = STROKE_WIDTH_CONVERSION
        * mix(u.frame_scale, 1.0, u.scale_stroke_with_zoom);
    let vw0 = vin.width0 * width_factor;
    let vw2 = vin.width2 * width_factor;

    let draw_flat = (u.flat_stroke != 0.0) || (u.is_fixed_in_frame != 0.0);

    // Coefficients such that the bezier is c0 + c1 * t + c2 * t^2
    let c0 = vin.p0;
    let c1 = 2.0 * (vin.p1 - vin.p0);
    let c2 = vin.p0 - 2.0 * vin.p1 + vin.p2;

    // Adaptive subdivision by control-triangle area
    let area = 0.5 * length(cross(vin.p1 - vin.p0, vin.p2 - vin.p0));
    let count = i32(round(POLYLINE_FACTOR * sqrt(area) / u.frame_scale));
    let n_steps = min(2 + count, MAX_STEPS);

    var i = i32(vid) / 2;
    if (i >= n_steps) { i = n_steps - 1; }  // clamp: degenerate tail
    var corner_sign = 1.0;
    if (i32(vid) % 2 == 0) { corner_sign = -1.0; }

    let t = f32(i) / f32(n_steps - 1);

    let point = point_on_quadratic(t, c0, c1, c2);
    let tangent = tangent_on_quadratic(t, c1, c2);

    let stroke_width = mix(vw0, vw2, t);
    let v_color = mix(vin.rgba0, vin.rgba2, t);

    let inside_curve = (i > 0 && i < n_steps - 1);

    var joint_angle: f32;
    if (i == 0) {
        joint_angle = -vin.ja0;
    } else if (inside_curve) {
        joint_angle = 0.0;
    } else {
        joint_angle = vin.ja2;
    }

    // emit_point_with_width, for one corner
    var unit_normal: vec3f;
    if (draw_flat) {
        unit_normal = vin.unit_normal1;
    } else {
        unit_normal = normalize(u.camera_position - point);
    }

    out.color = finalize_color(v_color, point, unit_normal);

    let step_dir = step_to_corner(point, tangent, unit_normal,
                                  vin.unit_normal1, joint_angle,
                                  inside_curve, draw_flat);
    let aaw = max(u.anti_alias_width * u.pixel_size, 1e-8);

    let dist_to_curve = corner_sign * 0.5 * (stroke_width + aaw);
    var offset_point = point + dist_to_curve * step_dir;
    // Small offset towards camera to prevent z-fighting with fill
    offset_point = offset_point + unit_normal * 0.0001;
    out.v_clip = compute_clip_distance(offset_point);
    out.position = emit_gl_position(offset_point);
    out.half_width_to_aaw = 0.5 * stroke_width / aaw;
    out.dist_to_aaw = dist_to_curve / aaw;
    return out;
}

@fragment
fn fs_main(vin: StrokeOut) -> @location(0) vec4f {
    if (vin.v_clip < 0.0) { discard; }
    var frag = vin.color;
    // sdf for the region around the curve we wish to color
    let signed_dist = abs(vin.dist_to_aaw) - vin.half_width_to_aaw;
    frag.a = frag.a * smoothstep(0.5, -0.5, signed_dist);
    if (u.border_mode > 0.5) {
        frag.a = frag.a * 0.95;
        frag = vec4f(frag.rgb * frag.a, frag.a);
    }
    return frag;
}
