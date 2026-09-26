// Source-space vector paint evaluation, shared by the paint pipeline and the
// patch fill's cover. The including file declares `paint` (the storage layout
// is defined by web/fill_paint.py); compile after common.wgsl.
fn source_paint(point: vec3f) -> vec4f {
    let local = (point - paint[0].xyz) / paint[0].w;
    let xy = vec2f(dot(local, paint[1].xyz), dot(local, paint[2].xyz));
    let count = u32(paint[1].w);
    let positive = paint[2].w != 0.0;
    var result = paint[3] + xy.x * paint[4] + xy.y * paint[5];
    var total = 0.0;
    if (positive) { result = vec4f(0.0); }
    for (var i = 0u; i < count; i += 1u) {
        let delta = xy - paint[6u + 2u * i].xy;
        let squared = dot(delta, delta);
        var weight = 0.5 * squared * log(max(squared, 1e-20));
        if (positive) { weight = 1.0 / max(squared, 1e-20); }
        result += weight * paint[7u + 2u * i];
        total += weight;
    }
    if (positive) { result /= total; }
    return clamp(result, vec4f(0.0), vec4f(1.0));
}

