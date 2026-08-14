// Port of quadratic_bezier/stroke/frag.glsl. border_mode replaces the
// "// MODIFY FRAG COLOR" string substitution that builds the
// fill-border variant in VShaderWrapper.

uniform float border_mode;

in float dist_to_aaw;
in float half_width_to_aaw;
in vec4 color;
in float v_clip;

out vec4 frag_color;

void main() {
    if (v_clip < 0.0) discard;
    frag_color = color;
    // sdf for the region around the curve we wish to color
    float signed_dist_to_region = abs(dist_to_aaw) - half_width_to_aaw;
    frag_color.a *= smoothstep(0.5, -0.5, signed_dist_to_region);
    if (border_mode > 0.5){
        frag_color.a *= 0.95;
        frag_color.rgb *= frag_color.a;
    }
}
