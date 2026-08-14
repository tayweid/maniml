// Shared uniforms + functions for the Stage-2 port of maniml's bezier
// pipeline. Ported from rendering/shaders/inserts/{emit_gl_Position,
// finalize_color}.glsl. Written in the common subset of GLSL 330 and
// GLSL 300 es: the loader prepends the #version line (and precision
// qualifiers for ES). Differences from the originals: no
// gl_ClipDistance (clip_plane unsupported in this path), and
// emit_gl_Position returns the position instead of assigning it.

uniform float is_fixed_in_frame;
uniform mat4 view;
uniform vec3 frame_rescale_factors;

uniform vec3 light_position;
uniform vec3 camera_position;
uniform vec3 shading;

vec4 emit_gl_Position(vec3 point){
    vec4 result = vec4(point, 1.0);
    // Smooth transitions between objects fixed and unfixed from frame
    result = mix(view * result, result, is_fixed_in_frame);
    // Essentially a projection matrix
    result.xyz *= frame_rescale_factors;
    result.w = 1.0 - result.z;
    // Flip and scale to prevent premature clipping
    result.z *= -0.1;
    // Fixed-in-frame objects render in front of everything else
    if (is_fixed_in_frame > 0.5){
        result.z = 0.09;
    }
    return result;
}

vec4 add_light(vec4 color, vec3 point, vec3 unit_normal){
    if (shading == vec3(0.0)) return color;

    float reflectiveness = shading.x;
    float gloss = shading.y;
    float shadow = shading.z;

    vec4 result = color;
    vec3 to_camera = normalize(camera_position - point);
    vec3 to_light = normalize(light_position - point);

    float light_to_normal = dot(to_light, unit_normal);
    float bright_factor = max(light_to_normal, 0.0) * reflectiveness;
    vec3 light_reflection = reflect(-to_light, unit_normal);
    float light_to_cam = dot(light_reflection, to_camera);
    float shine = gloss * exp(-3.0 * pow(1.0 - light_to_cam, 2.0));
    bright_factor += shine;

    result.rgb = mix(result.rgb, vec3(1.0), bright_factor);
    if (light_to_normal < 0.0){
        result.rgb = mix(
            result.rgb,
            vec3(0.0),
            max(-light_to_normal, 0.0) * shadow
        );
    }
    return result;
}

vec4 finalize_color(vec4 color, vec3 point, vec3 unit_normal){
    return add_light(color, point, unit_normal);
}

// Send skipped instances far outside the clip volume (the instanced
// stand-in for a geometry shader emitting nothing)
const vec4 DISCARD_POSITION = vec4(2.0e10, 2.0e10, 2.0e10, 1.0);
