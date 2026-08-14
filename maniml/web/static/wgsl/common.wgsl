// WebGPU port of web/static/glsl/common.glsl. One uniform struct
// serves every pipeline (WebGPU has no loose uniforms); the Python and
// JS sides pack it with matching layout — see UNIFORM_FIELDS in
// web/wgpu_renderer.py before touching field order.

struct Uniforms {
    view: mat4x4f,
    frame_rescale_factors: vec3f,
    is_fixed_in_frame: f32,
    camera_position: vec3f,
    frame_scale: f32,
    light_position: vec3f,
    pixel_size: f32,
    shading: vec3f,
    anti_alias_width: f32,
    clip_plane: vec4f,
    joint_type: f32,
    flat_stroke: f32,
    scale_stroke_with_zoom: f32,
    glow_factor: f32,
    num_textures: f32,
    border_mode: f32,
    _pad0: f32,
    _pad1: f32,
}
@group(0) @binding(0) var<uniform> u: Uniforms;

fn emit_gl_position(point: vec3f) -> vec4f {
    var result = vec4f(point, 1.0);
    // Smooth transitions between objects fixed and unfixed from frame
    result = mix(u.view * result, result, u.is_fixed_in_frame);
    // Essentially a projection matrix
    result = vec4f(result.xyz * u.frame_rescale_factors, result.w);
    result.w = 1.0 - result.z;
    // Flip and scale to prevent premature clipping
    result.z = result.z * -0.1;
    // Fixed-in-frame objects render in front of everything else
    if (u.is_fixed_in_frame > 0.5) {
        result.z = 0.09;
    }
    // GL clips z to [-w, w]; WebGPU clips to [0, w]. Remap so the GL
    // projection's depth semantics (ordering AND near/far clipping)
    // carry over exactly.
    result.z = (result.z + result.w) * 0.5;
    return result;
}

fn add_light(color: vec4f, point: vec3f, unit_normal: vec3f) -> vec4f {
    if (all(u.shading == vec3f(0.0))) {
        return color;
    }
    let reflectiveness = u.shading.x;
    let gloss = u.shading.y;
    let shadow = u.shading.z;

    var result = color;
    let to_camera = normalize(u.camera_position - point);
    let to_light = normalize(u.light_position - point);

    let light_to_normal = dot(to_light, unit_normal);
    var bright_factor = max(light_to_normal, 0.0) * reflectiveness;
    let light_reflection = reflect(-to_light, unit_normal);
    let light_to_cam = dot(light_reflection, to_camera);
    let shine = gloss * exp(-3.0 * pow(1.0 - light_to_cam, 2.0));
    bright_factor = bright_factor + shine;

    result = vec4f(mix(result.rgb, vec3f(1.0), bright_factor), result.a);
    if (light_to_normal < 0.0) {
        result = vec4f(
            mix(result.rgb, vec3f(0.0), max(-light_to_normal, 0.0) * shadow),
            result.a);
    }
    return result;
}

fn finalize_color(color: vec4f, point: vec3f, unit_normal: vec3f) -> vec4f {
    return add_light(color, point, unit_normal);
}

fn compute_clip_distance(point: vec3f) -> f32 {
    if (any(u.clip_plane.xyz != vec3f(0.0))) {
        return dot(vec4f(point, 1.0), u.clip_plane);
    }
    return 1.0;
}

// Send skipped instances far outside the clip volume (the instanced
// stand-in for a geometry shader emitting nothing)
const DISCARD_POSITION = vec4f(2.0e10, 2.0e10, 2.0e10, 1.0);
