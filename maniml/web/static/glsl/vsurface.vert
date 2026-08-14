// Port of surface/vert.glsl — serves the triangulated-fill path
// (depth-correct 3D fills). Plain vertex+fragment; no geometry shader
// involved. Normal comes from the offset point, as in the original.

in vec3 point;
in vec3 d_normal_point;
in vec4 rgba;

out vec4 v_color;
out float v_clip;

void main(){
    v_clip = compute_clip_distance(point);
    gl_Position = emit_gl_Position(point);
    vec3 unit_normal = normalize(d_normal_point - point);
    v_color = finalize_color(rgba, point, unit_normal);
}
