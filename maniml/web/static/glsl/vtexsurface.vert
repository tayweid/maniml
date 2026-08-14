// Port of textured_surface/vert.glsl (the unused is_sphere/center
// uniforms are dropped).

in vec3 point;
in vec3 d_normal_point;
in vec2 im_coords;
in float opacity;

out vec3 v_point;
out vec3 v_unit_normal;
out vec2 v_im_coords;
out float v_opacity;
out float v_clip;

void main(){
    v_point = point;
    v_unit_normal = normalize(d_normal_point - point);
    v_im_coords = im_coords;
    v_opacity = opacity;
    v_clip = compute_clip_distance(point);
    gl_Position = emit_gl_Position(point);
}
