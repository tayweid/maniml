// Instanced port of quadratic_bezier/stroke/{vert,geom}.glsl.
// One instance per bezier triple. The geometry shader's adaptive
// polyline (triangle_strip, up to MAX_STEPS point-pairs) becomes a
// fixed 64-vertex instanced strip: gl_VertexID/2 is the polyline step,
// gl_VertexID%2 picks the -/+ corner, and steps beyond the adaptive
// n_steps clamp to the last pair (degenerate, zero-area — the
// instanced stand-in for emitting fewer vertices).
// Serves both the stroke pass and the fill-border pass (same program,
// different attribute bindings + border_mode in the frag).

uniform float anti_alias_width;
uniform float flat_stroke;
uniform float pixel_size;
uniform float joint_type;
uniform float frame_scale;
uniform float scale_stroke_with_zoom;

// Per-instance attributes (stride = 3 x 68-byte vertex structs)
in vec3 p0;
in vec3 p1;
in vec3 p2;
in vec4 rgba0;
in vec4 rgba1;
in vec4 rgba2;
in float width0;
in float width1;
in float width2;
in float ja0;           // joint_angle of vertex 0
in float ja2;           // joint_angle of vertex 2
in vec3 unit_normal1;   // base_normal of vertex 1 (odd index: unit normal)

out vec4 color;
out float dist_to_aaw;
out float half_width_to_aaw;
out float v_clip;

// Codes for joint types
const int NO_JOINT = 0;
const int BEVEL_JOINT = 2;
const int MITER_JOINT = 3;

const float COS_THRESHOLD = 0.999;
const float POLYLINE_FACTOR = 100.0;
const int MAX_STEPS = 32;
const float MITER_COS_ANGLE_THRESHOLD = -0.8;
const float STROKE_WIDTH_CONVERSION = 0.01;

vec3 point_on_quadratic(float t, vec3 c0, vec3 c1, vec3 c2){
    return c0 + c1 * t + c2 * t * t;
}

vec3 tangent_on_quadratic(float t, vec3 c1, vec3 c2){
    return c1 + 2.0 * c2 * t;
}

vec3 project_onto_plane(vec3 vect, vec3 unit_normal){
    return vect - dot(vect, unit_normal) * unit_normal;
}

vec3 rotate_vector(vec3 vect, vec3 unit_normal, float angle){
    vec3 perp = cross(unit_normal, vect);
    return cos(angle) * vect + sin(angle) * perp;
}

vec3 step_to_corner(
    vec3 point, vec3 tangent, vec3 unit_normal,
    float joint_angle, bool inside_curve, bool draw_flat
){
    vec3 unit_tan = normalize(
        draw_flat ? tangent : project_onto_plane(tangent, unit_normal));

    vec3 step_dir = normalize(cross(unit_normal, unit_tan));

    if (joint_angle != 0.0){
        float alignment = abs(dot(normalize(tangent), unit_normal));
        float alignment_threshold = 0.97;
        if (alignment > alignment_threshold){
            vec3 perp = normalize(cross(unit_normal1, tangent));
            step_dir = mix(
                step_dir,
                project_onto_plane(step_dir, perp),
                smoothstep(alignment_threshold, 1.0, alignment)
            );
        }
    }

    if (inside_curve || int(joint_type) == NO_JOINT) return step_dir;

    float cos_angle = cos(joint_angle);
    float sin_angle = sin(joint_angle);

    if (abs(cos_angle) > COS_THRESHOLD) return step_dir;

    if (!draw_flat){
        step_dir = normalize(cross(unit_normal, unit_tan));
        vec3 adj_tan = rotate_vector(tangent, unit_normal1, joint_angle);
        adj_tan = project_onto_plane(adj_tan, unit_normal);
        cos_angle = dot(unit_tan, normalize(adj_tan));
        sin_angle = sqrt(1.0 - cos_angle * cos_angle)
            * sign(joint_angle) * sign(dot(unit_normal, unit_normal1));
    }

    float miter_factor;
    int jt = int(joint_type);
    if (jt == BEVEL_JOINT){
        miter_factor = 0.0;
    } else if (jt == MITER_JOINT){
        miter_factor = 1.0;
    } else {
        float mcat1 = MITER_COS_ANGLE_THRESHOLD;
        float mcat2 = mix(mcat1, -1.0, 0.5);
        miter_factor = smoothstep(mcat1, mcat2, cos_angle);
    }

    float shift = (cos_angle + mix(-1.0, 1.0, miter_factor)) / sin_angle;
    return step_dir + shift * unit_tan;
}

void main() {
    // Curves are marked as ended when the handle after
    // the first anchor is set equal to that anchor
    if (p0 == p1){
        gl_Position = DISCARD_POSITION;
        return;
    }
    // Check null stroke
    if (vec3(width0, width1, width2) == vec3(0.0)
            || vec3(rgba0.a, rgba1.a, rgba2.a) == vec3(0.0)){
        gl_Position = DISCARD_POSITION;
        return;
    }

    // The original vert stage's width conversion
    float width_factor = STROKE_WIDTH_CONVERSION
        * mix(frame_scale, 1.0, scale_stroke_with_zoom);
    float vw0 = width0 * width_factor;
    float vw2 = width2 * width_factor;

    bool draw_flat = bool(flat_stroke) || bool(is_fixed_in_frame);

    // Coefficients such that the bezier is c0 + c1 * t + c2 * t^2
    vec3 c0 = p0;
    vec3 c1 = 2.0 * (p1 - p0);
    vec3 c2 = p0 - 2.0 * p1 + p2;

    // Adaptive subdivision by control-triangle area
    float area = 0.5 * length(cross(p1 - p0, p2 - p0));
    int count = int(round(POLYLINE_FACTOR * sqrt(area) / frame_scale));
    int n_steps = min(2 + count, MAX_STEPS);

    int i = gl_VertexID / 2;
    if (i >= n_steps) i = n_steps - 1;  // clamp: degenerate tail
    float corner_sign = (gl_VertexID % 2 == 0) ? -1.0 : 1.0;

    float t = float(i) / float(n_steps - 1);

    vec3 point = point_on_quadratic(t, c0, c1, c2);
    vec3 tangent = tangent_on_quadratic(t, c1, c2);

    float stroke_width = mix(vw0, vw2, t);
    vec4 v_color = mix(rgba0, rgba2, t);

    bool inside_curve = (i > 0 && i < n_steps - 1);

    float joint_angle;
    if (i == 0){
        joint_angle = -ja0;
    } else if (inside_curve){
        joint_angle = 0.0;
    } else {
        joint_angle = ja2;
    }

    // emit_point_with_width, for one corner
    vec3 unit_normal = draw_flat
        ? unit_normal1 : normalize(camera_position - point);

    color = finalize_color(v_color, point, unit_normal);

    vec3 step_dir = step_to_corner(
        point, tangent, unit_normal, joint_angle, inside_curve, draw_flat);
    float aaw = max(anti_alias_width * pixel_size, 1e-8);

    float dist_to_curve = corner_sign * 0.5 * (stroke_width + aaw);
    vec3 offset_point = point + dist_to_curve * step_dir;
    // Small offset towards camera to prevent z-fighting with fill
    offset_point += unit_normal * 0.0001;
    v_clip = compute_clip_distance(offset_point);
    gl_Position = emit_gl_Position(offset_point);
    half_width_to_aaw = 0.5 * stroke_width / aaw;
    dist_to_aaw = dist_to_curve / aaw;
}
