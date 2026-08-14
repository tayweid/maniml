// Port of the inline simple_vert in shader_wrapper.get_fill_canvas.

in vec2 texcoord;
out vec2 uv;

void main() {
    gl_Position = vec4(2.0 * texcoord - 1.0, 0.0, 1.0);
    uv = texcoord;
}
