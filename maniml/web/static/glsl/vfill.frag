// Port of quadratic_bezier/fill/frag.glsl (the unused `winding`
// uniform is dropped).

in vec4 color;
in float fill_all;
in float orientation;
in vec2 uv_coords;
in float v_clip;

out vec4 frag_color;

void main() {
    if (v_clip < 0.0) discard;
    if (color.a == 0.0) discard;
    frag_color = color;
    // Winding-number-via-blending trick: negatively oriented triangles
    // get alpha -a/(1-a) so blending cancels a positive one exactly;
    // 0.95 caps the singularity at a=1 (see the original's comment)
    float a = 0.95 * frag_color.a;
    if (orientation < 0.0) a = -a / (1.0 - a);
    frag_color.a = a;

    if (fill_all > 0.5) return;

    float x = uv_coords.x;
    float y = uv_coords.y;
    float Fxy = (y - x * x);
    if (Fxy < 0.0) discard;
}
