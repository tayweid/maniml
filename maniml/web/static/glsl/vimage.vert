// Port of image/vert.glsl (ImageMobject).

in vec3 point;
in vec2 im_coords;
in float opacity;

out vec2 v_im_coords;
out float v_opacity;
out float v_clip;

void main(){
    v_im_coords = im_coords;
    v_opacity = opacity;
    v_clip = compute_clip_distance(point);
    gl_Position = emit_gl_Position(point);
}
