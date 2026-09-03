// Instanced winding-number fill. One instance per bezier triple, 6 vertices
// reproducing the geometry shader's two triangles.

struct FillIn {
    @location(0) p0: vec3f,
    @location(1) p1: vec3f,
    @location(2) p2: vec3f,
    @location(3) c0: vec4f,
    @location(4) c1: vec4f,
    @location(5) c2: vec4f,
    @location(6) base_point: vec3f,
    @location(7) unit_normal: vec3f,
}

struct FillOut {
    @builtin(position) position: vec4f,
    @location(0) color: vec4f,
    @location(1) fill_all: f32,
    @location(2) orientation: f32,
    @location(3) uv_coords: vec2f,
    @location(4) v_clip: f32,
}

@vertex
fn vs_main(vin: FillIn, @builtin(vertex_index) vid: u32) -> FillOut {
    var out: FillOut;
    // Curves are marked as ended when the handle after the first
    // anchor is set equal to that anchor; also skip zero fill
    if (all(vin.p0 == vin.p1)
            || (vin.c0.a == 0.0 && vin.c1.a == 0.0 && vin.c2.a == 0.0)) {
        out.position = DISCARD_POSITION;
        return out;
    }

    let tri = i32(vid) / 3;
    let corner = i32(vid) % 3;

    var simple_quadratic = array<vec2f, 3>(
        vec2f(0.0, 0.0), vec2f(0.5, 0.0), vec2f(1.0, 1.0));

    var points: array<vec3f, 3>;
    var colors: array<vec4f, 3>;
    if (tri == 0) {
        points[0] = vin.base_point; points[1] = vin.p0; points[2] = vin.p2;
        colors[0] = vin.c1; colors[1] = vin.c0; colors[2] = vin.c2;
        out.fill_all = 1.0;
    } else {
        points[0] = vin.p0; points[1] = vin.p1; points[2] = vin.p2;
        colors[0] = vin.c0; colors[1] = vin.c1; colors[2] = vin.c2;
        out.fill_all = 0.0;
    }

    out.orientation = sign(determinant(mat3x3f(
        vin.unit_normal,
        points[1] - points[0],
        points[2] - points[0]
    )));

    out.uv_coords = simple_quadratic[corner];
    out.color = finalize_color(colors[corner], points[corner],
                               vin.unit_normal);
    out.v_clip = compute_clip_distance(points[corner]);
    out.position = emit_gl_position(points[corner]);
    return out;
}

@fragment
fn fs_main(vin: FillOut) -> @location(0) vec4f {
    if (vin.v_clip < 0.0) { discard; }
    if (vin.color.a == 0.0) { discard; }
    var frag = vin.color;
    // Winding-number-via-blending: negative orientations get alpha
    // -a/(1-a) so blending cancels a positive one exactly; 0.95 caps
    // the singularity at a=1
    var a = 0.95 * frag.a;
    if (vin.orientation < 0.0) {
        a = -a / (1.0 - a);
    }
    frag.a = a;

    if (vin.fill_all > 0.5) {
        return frag;
    }
    let x = vin.uv_coords.x;
    let y = vin.uv_coords.y;
    if (y - x * x < 0.0) { discard; }
    return frag;
}
