// Port of the inline alpha_adjust_frag in shader_wrapper.get_fill_canvas,
// minus the depth-texture logic (this path only serves non-depth-tested
// 2D fills; depth-tested batches are excluded at serialization).

uniform sampler2D Texture;

in vec2 uv;
out vec4 color;

void main() {
    color = texture(Texture, uv);
    if (color.a == 0.0) discard;

    if (color.a < 0.0){
        color.a = -color.a / (1.0 - color.a);
        color.rgb *= (color.a - 1.0);
    }

    // Counteract scaling in fill frag
    color *= 1.06;
}
