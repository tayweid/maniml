// Port of image/frag.glsl.

uniform sampler2D Texture;

in vec2 v_im_coords;
in float v_opacity;
in float v_clip;

out vec4 frag_color;

void main() {
    if (v_clip < 0.0) discard;
    frag_color = texture(Texture, v_im_coords);
    frag_color.a *= v_opacity;
}
