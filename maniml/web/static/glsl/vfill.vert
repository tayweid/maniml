// Instanced port of quadratic_bezier/fill/{vert,geom}.glsl.
// One instance per bezier triple; 6 vertices per instance reproduce the
// two triangles the geometry shader emitted: the "fill_all" triangle
// (base_point, p0, p2) and the edge triangle (p0, p1, p2).

// Per-instance attributes (stride = 3 x 68-byte vertex structs)
in vec3 p0;
in vec3 p1;
in vec3 p2;
in vec4 c0;
in vec4 c1;
in vec4 c2;
in vec3 base_point;   // base_normal of vertex 0 (even index: base point)
in vec3 unit_normal;  // base_normal of vertex 1 (odd index: unit normal)

out vec4 color;
out float fill_all;
out float orientation;
// uv space is where the curve coincides with y = x^2
out vec2 uv_coords;
out float v_clip;

void main(){
    // Curves are marked as ended when the handle after
    // the first anchor is set equal to that anchor
    if (p0 == p1){
        gl_Position = DISCARD_POSITION;
        return;
    }
    // Check zero fill
    if (vec3(c0.a, c1.a, c2.a) == vec3(0.0)){
        gl_Position = DISCARD_POSITION;
        return;
    }

    int tri = gl_VertexID / 3;
    int corner = gl_VertexID % 3;

    vec2 SIMPLE_QUADRATIC[3];
    SIMPLE_QUADRATIC[0] = vec2(0.0, 0.0);
    SIMPLE_QUADRATIC[1] = vec2(0.5, 0.0);
    SIMPLE_QUADRATIC[2] = vec2(1.0, 1.0);

    vec3 points[3];
    vec4 colors[3];
    if (tri == 0){
        points[0] = base_point; points[1] = p0; points[2] = p2;
        colors[0] = c1; colors[1] = c0; colors[2] = c2;
        fill_all = 1.0;
    } else {
        points[0] = p0; points[1] = p1; points[2] = p2;
        colors[0] = c0; colors[1] = c1; colors[2] = c2;
        fill_all = 0.0;
    }

    orientation = sign(determinant(mat3(
        unit_normal,
        points[1] - points[0],
        points[2] - points[0]
    )));

    uv_coords = SIMPLE_QUADRATIC[corner];
    color = finalize_color(colors[corner], points[corner], unit_normal);
    v_clip = compute_clip_distance(points[corner]);
    gl_Position = emit_gl_Position(points[corner]);
}
