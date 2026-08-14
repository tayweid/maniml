// Instanced port of true_dot/{vert,geom}.glsl. One instance per dot;
// 4 vertices reproduce the camera-facing billboard quad the geometry
// shader emitted. Attributes are prefixed dot_ because the fragment
// shader's varyings reuse the original names (point, radius).

uniform float pixel_size;
uniform float anti_alias_width;

// Per-instance attributes (stride = 32-byte DotCloud vertex struct)
in vec3 dot_point;
in float dot_radius;
in vec4 dot_rgba;

out vec4 color;
out float scaled_aaw;
out vec3 point;
out vec3 to_cam;
out vec3 center;
out float radius;
out vec2 uv_coords;

void main(){
    color = dot_rgba;
    radius = dot_radius;
    center = dot_point;
    scaled_aaw = (anti_alias_width * pixel_size) / dot_radius;

    to_cam = normalize(camera_position - dot_point);
    vec3 right = dot_radius * normalize(cross(vec3(0.0, 1.0, 1.0), to_cam));
    vec3 up = dot_radius * normalize(cross(to_cam, right));

    // Geometry shader's loop order: i=-1 (j=-1, j=+1), i=+1 (j=-1, j=+1)
    float fi = (gl_VertexID < 2) ? -1.0 : 1.0;
    float fj = (gl_VertexID % 2 == 0) ? -1.0 : 1.0;

    point = dot_point + fi * right + fj * up;
    uv_coords = vec2(fi, fj);
    gl_Position = emit_gl_Position(point);
}
