// Port of surface/frag.glsl.

in vec4 v_color;
in float v_clip;
out vec4 frag_color;

void main() {
    if (v_clip < 0.0) discard;
    frag_color = v_color;
}
