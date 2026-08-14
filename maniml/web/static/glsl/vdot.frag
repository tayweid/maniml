// Port of true_dot/frag.glsl (the unused `perspective` uniform is
// dropped). Compiled with common.glsl for finalize_color/shading.

uniform float glow_factor;

in vec4 color;
in float scaled_aaw;
in vec3 point;
in vec3 to_cam;
in vec3 center;
in float radius;
in vec2 uv_coords;

out vec4 frag_color;

void main() {
    float r = length(uv_coords.xy);
    if (r > 1.0) discard;

    frag_color = color;

    if (glow_factor > 0.0){
        frag_color.a *= pow(1.0 - r, glow_factor);
    }

    if (shading != vec3(0.0)){
        vec3 point_3d = point + radius * sqrt(1.0 - r * r) * to_cam;
        vec3 normal = normalize(point_3d - center);
        frag_color = finalize_color(frag_color, point_3d, normal);
    }

    frag_color.a *= smoothstep(1.0, 1.0 - scaled_aaw, r);
}
