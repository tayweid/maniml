// Port of textured_surface/frag.glsl. Compiled with common.glsl for
// finalize_color / light_position.

uniform sampler2D LightTexture;
uniform sampler2D DarkTexture;
uniform float num_textures;

in vec3 v_point;
in vec3 v_unit_normal;
in vec2 v_im_coords;
in float v_opacity;

out vec4 frag_color;

const float dark_shift = 0.2;

void main() {
    vec4 color = texture(LightTexture, v_im_coords);
    if (num_textures == 2.0){
        vec4 dark_color = texture(DarkTexture, v_im_coords);
        float dp = dot(
            normalize(light_position - v_point),
            v_unit_normal
        );
        float alpha = smoothstep(-dark_shift, dark_shift, dp);
        color = mix(dark_color, color, alpha);
    }
    if (color.a == 0.0) discard;

    frag_color = finalize_color(
        color,
        v_point,
        v_unit_normal
    );
    frag_color.a = v_opacity;
}
