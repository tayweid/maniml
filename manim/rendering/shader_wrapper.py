from __future__ import annotations

import copy
import os
import re

import OpenGL.GL as gl
import moderngl
import numpy as np
from functools import lru_cache

from manim.config import parse_cli
from manim.config import manim_config
from manim.utils.shaders import get_shader_code_from_file
from manim.utils.shaders import get_shader_program
from manim.utils.shaders import image_path_to_texture
from manim.utils.shaders import set_program_uniform

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional, Tuple, Iterable
    from manim.typing import UniformDict
    from moderngl.vertex_array import VertexArray
    from moderngl.framebuffer import Framebuffer

# Mobjects that should be rendered with
# the same shader will be organized and
# clumped together based on keeping track
# of a dict holding all the relevant information
# to that shader


class ShaderWrapper(object):
    def __init__(
        self,
        ctx: moderngl.context.Context,
        vert_data: np.ndarray,
        shader_folder: Optional[str] = None,
        mobject_uniforms: Optional[UniformDict] = None,  # A dictionary mapping names of uniform variables
        texture_paths: Optional[dict[str, str]] = None,  # A dictionary mapping names to filepaths for textures.
        depth_test: bool = False,
        render_primitive: int = moderngl.TRIANGLE_STRIP,
        code_replacements: dict[str, str] = dict(),
    ):
        self.ctx = ctx
        self.vert_data = vert_data
        self.vert_attributes = vert_data.dtype.names
        self.shader_folder = shader_folder
        self.depth_test = depth_test
        self.render_primitive = render_primitive
        self.texture_paths = texture_paths or dict()

        self.program_uniform_mirror: UniformDict = dict()
        self.bind_to_mobject_uniforms(mobject_uniforms or dict())

        self.init_program_code()
        for old, new in code_replacements.items():
            self.replace_code(old, new)
        self.init_program()
        self.init_textures()
        self.init_vertex_objects()
        self.refresh_id()

    def __deepcopy__(self, memo):
        # Don't allow deepcopies, e.g. if the mobject with this ShaderWrapper as an
        # attribute gets copies. Returning None means the parent object with this ShaderWrapper
        # as an attribute should smoothly handle this case.
        return None

    def init_program_code(self) -> None:
        def get_code(name: str) -> str | None:
            return get_shader_code_from_file(
                os.path.join(self.shader_folder, f"{name}.glsl")
            )

        self.program_code: dict[str, str | None] = {
            "vertex_shader": get_code("vert"),
            "geometry_shader": get_code("geom"),
            "fragment_shader": get_code("frag"),
        }

    def init_program(self):
        if not self.shader_folder:
            self.program = None
            self.vert_format = None
            self.programs = []
            return
        self.program = get_shader_program(self.ctx, **self.program_code)
        self.vert_format = moderngl.detect_format(self.program, self.vert_attributes)
        self.programs = [self.program]

    def init_textures(self):
        self.texture_names_to_ids = dict()
        self.textures = []
        for name, path in self.texture_paths.items():
            self.add_texture(name, image_path_to_texture(path, self.ctx))

    def init_vertex_objects(self):
        self.vbo = None
        self.vaos = []

    def add_texture(self, name: str, texture: moderngl.Texture):
        max_units = self.ctx.info['GL_MAX_TEXTURE_IMAGE_UNITS']
        if len(self.textures) >= max_units:
            raise ValueError(f"Unable to use more than {max_units} textures for a program")
        # The position in the list determines its id
        self.texture_names_to_ids[name] = len(self.textures)
        self.textures.append(texture)

    def bind_to_mobject_uniforms(self, mobject_uniforms: UniformDict):
        self.mobject_uniforms = mobject_uniforms

    def get_id(self) -> int:
        return self.id

    def refresh_id(self) -> None:
        self.id = hash("".join(map(str, [
            "".join(map(str, self.program_code.values())),
            self.mobject_uniforms,
            self.depth_test,
            self.render_primitive,
            self.texture_paths,
        ])))

    def replace_code(self, old: str, new: str) -> None:
        code_map = self.program_code
        for name in code_map:
            if code_map[name] is None:
                continue
            code_map[name] = re.sub(old, new, code_map[name])
        self.init_program()
        self.refresh_id()

    # Changing context
    def use_clip_plane(self):
        if "clip_plane" not in self.mobject_uniforms:
            return False
        return any(self.mobject_uniforms["clip_plane"])

    def set_ctx_depth_test(self, enable: bool = True) -> None:
        if enable:
            self.ctx.enable(moderngl.DEPTH_TEST)
        else:
            self.ctx.disable(moderngl.DEPTH_TEST)

    def set_ctx_clip_plane(self, enable: bool = True) -> None:
        if enable:
            gl.glEnable(gl.GL_CLIP_DISTANCE0)

    # Adding data

    def read_in(self, data_list: Iterable[np.ndarray]):
        total_len = sum(map(len, data_list))
        if total_len == 0:
            if self.vbo is not None:
                self.vbo.clear()
            return

        # If possible, read concatenated data into existing list
        if len(self.vert_data) != total_len:
            self.vert_data = np.concatenate(data_list)
        else:
            np.concatenate(data_list, out=self.vert_data)

        # Either create new vbo, or read data into it
        total_size = self.vert_data.itemsize * total_len
        if self.vbo is not None and self.vbo.size != total_size:
            self.release()  # This sets vbo to be None
        if self.vbo is None:
            self.vbo = self.ctx.buffer(self.vert_data)
            self.generate_vaos()
        else:
            self.vbo.write(self.vert_data)

    def generate_vaos(self):
        # Vertex array object
        self.vaos = [
            self.ctx.vertex_array(
                program=program,
                content=[(self.vbo, self.vert_format, *self.vert_attributes)],
                mode=self.render_primitive,
            )
            for program in self.programs
        ]

    # Related to data and rendering
    def pre_render(self):
        self.set_ctx_depth_test(self.depth_test)
        self.set_ctx_clip_plane(self.use_clip_plane())
        for tid, texture in enumerate(self.textures):
            texture.use(tid)

    def render(self):
        for vao in self.vaos:
            vao.render()

    def update_program_uniforms(self, camera_uniforms: UniformDict):
        for program in self.programs:
            if program is None:
                continue
            for uniforms in [self.mobject_uniforms, camera_uniforms, self.texture_names_to_ids]:
                for name, value in uniforms.items():
                    set_program_uniform(program, name, value)

    def release(self):
        for obj in (self.vbo, *self.vaos):
            if obj is not None:
                obj.release()
        self.init_vertex_objects()

    def release_textures(self):
        for texture in self.textures:
            texture.release()
            del texture
        self.textures = []
        self.texture_names_to_ids = dict()


class VShaderWrapper(ShaderWrapper):
    def __init__(
        self,
        ctx: moderngl.context.Context,
        vert_data: np.ndarray,
        shader_folder: Optional[str] = None,
        mobject_uniforms: Optional[UniformDict] = None,  # A dictionary mapping names of uniform variables
        texture_paths: Optional[dict[str, str]] = None,  # A dictionary mapping names to filepaths for textures.
        depth_test: bool = False,
        render_primitive: int = moderngl.TRIANGLES,
        code_replacements: dict[str, str] = dict(),
        stroke_behind: bool = False,
    ):
        self.stroke_behind = stroke_behind
        super().__init__(
            ctx=ctx,
            vert_data=vert_data,
            shader_folder=shader_folder,
            mobject_uniforms=mobject_uniforms,
            texture_paths=texture_paths,
            depth_test=depth_test,
            render_primitive=render_primitive,
            code_replacements=code_replacements,
        )
        self.fill_canvas = VShaderWrapper.get_fill_canvas(self.ctx)
        self.add_texture('Texture', self.fill_canvas[0].color_attachments[0])
        self.add_texture('DepthTexture', self.fill_canvas[2].color_attachments[0])

    def init_program_code(self) -> None:
        self.program_code = {
            f"{vtype}_{name}": get_shader_code_from_file(
                os.path.join("quadratic_bezier", f"{vtype}", f"{name}.glsl")
            )
            for vtype in ["stroke", "fill", "depth"]
            for name in ["vert", "geom", "frag"]
        }

    def init_program(self):
        self.stroke_program = get_shader_program(
            self.ctx,
            vertex_shader=self.program_code["stroke_vert"],
            geometry_shader=self.program_code["stroke_geom"],
            fragment_shader=self.program_code["stroke_frag"],
        )
        self.fill_program = get_shader_program(
            self.ctx,
            vertex_shader=self.program_code["fill_vert"],
            geometry_shader=self.program_code["fill_geom"],
            fragment_shader=self.program_code["fill_frag"],
        )
        self.fill_border_program = get_shader_program(
            self.ctx,
            vertex_shader=self.program_code["stroke_vert"],
            geometry_shader=self.program_code["stroke_geom"],
            fragment_shader=self.program_code["stroke_frag"].replace(
                "// MODIFY FRAG COLOR",
                "frag_color.a *= 0.95; frag_color.rgb *= frag_color.a;",
            )
        )
        self.fill_depth_program = get_shader_program(
            self.ctx,
            vertex_shader=self.program_code["depth_vert"],
            geometry_shader=self.program_code["depth_geom"],
            fragment_shader=self.program_code["depth_frag"],
        )
        self.programs = [self.stroke_program, self.fill_program, self.fill_border_program, self.fill_depth_program]

        # Full vert format looks like this (total of 4x23 = 92 bytes):
        # point 3
        # stroke_rgba 4
        # stroke_width 1
        # joint_angle 1
        # fill_rgba 4
        # base_normal 3
        # fill_border_width 1
        self.stroke_vert_format = '3f 4f 1f 1f 16x 3f 4x'
        self.stroke_vert_attributes = ['point', 'stroke_rgba', 'stroke_width', 'joint_angle', 'unit_normal']

        self.fill_vert_format = '3f 24x 4f 3f 4x'
        self.fill_vert_attributes = ['point', 'fill_rgba', 'base_normal']

        self.fill_border_vert_format = '3f 20x 1f 4f 3f 1f'
        self.fill_border_vert_attributes = ['point', 'joint_angle', 'stroke_rgba', 'unit_normal', 'stroke_width']

        self.fill_depth_vert_format = '3f 40x 3f 4x'
        self.fill_depth_vert_attributes = ['point', 'base_normal']

    def init_vertex_objects(self):
        self.vbo = None
        self.stroke_vao = None
        self.fill_vao = None
        self.fill_border_vao = None
        self.vaos = []

    def generate_vaos(self):
        self.stroke_vao = self.ctx.vertex_array(
            program=self.stroke_program,
            content=[(self.vbo, self.stroke_vert_format, *self.stroke_vert_attributes)],
            mode=self.render_primitive,
        )
        self.fill_vao = self.ctx.vertex_array(
            program=self.fill_program,
            content=[(self.vbo, self.fill_vert_format, *self.fill_vert_attributes)],
            mode=self.render_primitive,
        )
        self.fill_border_vao = self.ctx.vertex_array(
            program=self.fill_border_program,
            content=[(self.vbo, self.fill_border_vert_format, *self.fill_border_vert_attributes)],
            mode=self.render_primitive,
        )
        self.fill_depth_vao = self.ctx.vertex_array(
            program=self.fill_depth_program,
            content=[(self.vbo, self.fill_depth_vert_format, *self.fill_depth_vert_attributes)],
            mode=self.render_primitive,
        )
        self.vaos = [self.stroke_vao, self.fill_vao, self.fill_border_vao, self.fill_depth_vao]

    def set_backstroke(self, value: bool = True):
        self.stroke_behind = value

    def refresh_id(self):
        super().refresh_id()
        self.id = hash(str(self.id) + str(self.stroke_behind))

    # Rendering
    def render_stroke(self):
        if self.stroke_vao is None:
            return
        self.stroke_vao.render()

    def render_fill(self):
        # Check if we should use triangulated fill
        if hasattr(self.mobject, 'use_triangulated_fill') and self.mobject.use_triangulated_fill:
            self.render_triangulated_fill()
            return
            
        if self.fill_vao is None:
            return

        original_fbo = self.ctx.fbo
        fill_tx_fbo, fill_tx_vao, depth_tx_fbo = self.fill_canvas

        # Render to a separate texture, due to strange alpha compositing
        # for the blended winding calculation
        fill_tx_fbo.clear()
        fill_tx_fbo.use()

        # Be sure not to apply depth test while rendering fill
        # but set it back to where it was after
        apply_depth_test = bool(gl.glGetBooleanv(gl.GL_DEPTH_TEST))
        self.ctx.disable(moderngl.DEPTH_TEST)

        # With this blend function, the effect of blending alpha a with
        # -a / (1 - a) cancels out, so we can cancel positively and negatively
        # oriented triangles
        gl.glBlendFuncSeparate(
            gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA,
            gl.GL_ONE_MINUS_DST_ALPHA, gl.GL_ONE
        )
        self.fill_vao.render()

        if apply_depth_test:
            self.ctx.enable(moderngl.DEPTH_TEST)
            depth_tx_fbo.clear(1.0)
            depth_tx_fbo.use()
            gl.glBlendFunc(gl.GL_ONE, gl.GL_ONE)
            gl.glBlendEquation(gl.GL_MIN)
            self.fill_depth_vao.render()
            # Important: restore to fill texture for border rendering
            fill_tx_fbo.use()

        # Now add border, just taking the max alpha
        gl.glBlendFunc(gl.GL_ONE, gl.GL_ONE)
        gl.glBlendEquation(gl.GL_MAX)
        self.fill_border_vao.render()

        # Take the texture we were just drawing to, and render it to
        # the main scene. Account for how alphas have been premultiplied
        original_fbo.use()
        gl.glBlendFunc(gl.GL_ONE, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glBlendEquation(gl.GL_FUNC_ADD)
        
        # If depth test is enabled, we need to enable it for the final composite
        # so that the fill respects the depth buffer of the main scene
        if apply_depth_test:
            self.ctx.enable(moderngl.DEPTH_TEST)
            # Also ensure depth writing is enabled
            gl.glDepthMask(gl.GL_TRUE)
        
        # Bind the textures to the shader
        # Get the textures from the framebuffers
        fill_texture = fill_tx_fbo.color_attachments[0]
        depth_texture = depth_tx_fbo.color_attachments[0]
        
        # Bind them to texture units
        fill_texture.use(location=0)
        depth_texture.use(location=1)
        
        # Get the shader program from the VAO and set the uniform values
        program = fill_tx_vao.program
        if 'Texture' in program:
            program['Texture'] = 0
        if 'DepthTexture' in program:
            program['DepthTexture'] = 1
        
        fill_tx_vao.render()
        
        # Restore depth test state if we changed it
        if apply_depth_test and not self.depth_test:
            self.ctx.disable(moderngl.DEPTH_TEST)

        # Return to original blending state
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)

    def render_triangulated_fill(self):
        """
        Render fill using triangulation for proper 3D depth testing.
        Uses the Surface rendering approach for simple, fast triangle rendering.
        """
        if not hasattr(self.mobject, 'get_fill_color'):
            return
            
        # Only render if there's actual fill
        if self.mobject.get_fill_opacity() == 0:
            return
            
        # Import here to avoid circular imports
        from manim.utils.color import color_to_rgb
        from manim.utils.shaders import get_shader_program
        
        # Check if we have cached triangulation data
        if not hasattr(self.mobject, '_triangulation_cache'):
            from manim.mobject.types.vmobject_3d import VMobject3D
            
            # Create a temporary VMobject3D from our mobject
            # This handles all the complex bezier-to-polygon conversion
            temp_3d = VMobject3D(
                self.mobject,
                color=self.mobject.get_fill_color(),
                opacity=self.mobject.get_fill_opacity()
            )
            
            # Check if triangulation succeeded
            if not hasattr(temp_3d, 'triangle_indices') or len(temp_3d.triangle_indices) == 0:
                return
                
            # Cache the triangulation data on the mobject
            self.mobject._triangulation_cache = {
                'vertices': temp_3d.get_points().copy(),
                'indices': temp_3d.triangle_indices.copy()
            }
        
        # Get the cached triangulated data
        vertices = self.mobject._triangulation_cache['vertices']
        triangle_indices = self.mobject._triangulation_cache['indices']
        
        if len(vertices) == 0:
            return
            
        # Create data array matching the Surface data structure
        # Surface expects: (point, d_normal_point, rgba)
        surface_dtype = np.dtype([
            ('point', np.float32, (3,)),
            ('d_normal_point', np.float32, (3,)),
            ('rgba', np.float32, (4,)),
        ])
        
        num_vertices = len(vertices)
        surface_data = np.zeros(num_vertices, dtype=surface_dtype)
        
        # Set vertex positions
        surface_data['point'][:] = vertices
        
        # For 2D objects, normals point in the +z direction
        # d_normal_point is slightly offset from the point in the normal direction
        normal_offset = 0.001  # Small offset for normal calculation
        surface_data['d_normal_point'][:] = vertices + np.array([0, 0, normal_offset])
        
        # Set color and opacity
        fill_color = self.mobject.get_fill_color()
        fill_opacity = self.mobject.get_fill_opacity()
        fill_rgb = color_to_rgb(fill_color)
        fill_rgba = np.array([*fill_rgb, fill_opacity], dtype=np.float32)
        surface_data['rgba'][:] = fill_rgba
        
        # Get or create surface shader program
        if not hasattr(self, '_surface_program'):
            # Load surface shader
            from manim.utils.shaders import get_shader_code_from_file
            vertex_shader = get_shader_code_from_file(
                os.path.join("surface", "vert.glsl")
            )
            fragment_shader = get_shader_code_from_file(
                os.path.join("surface", "frag.glsl")
            )
            self._surface_program = get_shader_program(
                self.ctx,
                vertex_shader=vertex_shader,
                fragment_shader=fragment_shader
            )
        
        # Create temporary buffers
        vbo = self.ctx.buffer(surface_data)
        ibo = self.ctx.buffer(np.array(triangle_indices, dtype='i4'))
        
        # Create vertex array
        vert_format = '3f 3f 4f'  # point, d_normal_point, rgba
        vert_attributes = ['point', 'd_normal_point', 'rgba']
        vao = self.ctx.vertex_array(
            program=self._surface_program,
            content=[(vbo, vert_format, *vert_attributes)],
            index_buffer=ibo,
            mode=moderngl.TRIANGLES
        )
        
        # Update uniforms on the surface program
        # The camera uniforms were already set on our programs by update_program_uniforms
        # We need to set them on this program too
        for program in self.programs:
            if program and program._members:
                # Copy uniform values from the fill program to surface program
                for name, member in program._members.items():
                    if hasattr(member, 'value') and name in self._surface_program:
                        try:
                            self._surface_program[name].value = member.value
                        except:
                            pass
                break
        
        # Also set mobject uniforms
        from manim.utils.shaders import set_program_uniform
        for name, value in self.mobject_uniforms.items():
            set_program_uniform(self._surface_program, name, value)
        
        # Enable depth testing
        self.ctx.enable(moderngl.DEPTH_TEST)
        
        # Render the triangles
        vao.render()
        
        # Clean up
        vao.release()
        vbo.release()
        ibo.release()

    # Static method returning one shared value across all VShaderWrappers
    @lru_cache
    @staticmethod
    def get_fill_canvas(ctx: moderngl.Context) -> Tuple[Framebuffer, VertexArray, Framebuffer]:
        """
        Because VMobjects with fill are rendered in a funny way, using
        alpha blending to effectively compute the winding number around
        each pixel, they need to be rendered to a separate texture, which
        is then composited onto the ordinary frame buffer.

        This returns a texture, loaded into a frame buffer, and a vao
        which can display that texture as a simple quad onto a screen,
        along with the rgb value which is meant to be discarded.
        """
        size = manim_config.camera.resolution
        double_size = (2 * size[0], 2 * size[1])

        # Important to make sure dtype is floating point (not fixed point)
        # so that alpha values can be negative and are not clipped
        fill_texture = ctx.texture(size=double_size, components=4, dtype='f2')
        # Use another one to keep track of depth - must match fill texture size!
        depth_texture = ctx.texture(size=double_size, components=1, dtype='f4')

        fill_texture_fbo = ctx.framebuffer(fill_texture)
        depth_texture_fbo = ctx.framebuffer(depth_texture)

        simple_vert = '''
            #version 330

            in vec2 texcoord;
            out vec2 uv;

            void main() {
                // Keep the quad in screen space but allow depth to be interpolated
                gl_Position = vec4((2.0 * texcoord - 1.0), 0.0, 1.0);
                uv = texcoord;
            }
        '''
        alpha_adjust_frag = '''
            #version 330

            uniform sampler2D Texture;
            uniform sampler2D DepthTexture;

            in vec2 uv;
            out vec4 color;

            void main() {
                color = texture(Texture, uv);
                if(color.a == 0) discard;

                if(color.a < 0){
                    color.a = -color.a / (1.0 - color.a);
                    color.rgb *= (color.a - 1);
                }

                // Counteract scaling in fill frag
                color *= 1.06;

                // Read depth from depth texture
                float depth = texture(DepthTexture, uv).r;
                
                // The depth texture contains gl_FragCoord.z values from the fill rendering pass
                // We need to ensure this depth value is properly used
                // If depth is 1.0 (default clear value), discard to avoid z-fighting
                if(depth >= 0.9999) {
                    discard;
                } else {
                    gl_FragDepth = depth;
                }
            }
        '''
        fill_program = ctx.program(
            vertex_shader=simple_vert,
            fragment_shader=alpha_adjust_frag,
        )

        verts = np.array([[0, 0], [0, 1], [1, 0], [1, 1]])
        simple_vbo = ctx.buffer(verts.astype('f4').tobytes())
        fill_texture_vao = ctx.simple_vertex_array(
            fill_program, simple_vbo, 'texcoord',
            mode=moderngl.TRIANGLE_STRIP
        )

        return (fill_texture_fbo, fill_texture_vao, depth_texture_fbo)

    def render(self):
        # Ensure pre_render is called to set depth test state
        self.pre_render()
        
        if self.stroke_behind:
            self.render_stroke()
            self.render_fill()
        else:
            self.render_fill()
            self.render_stroke()
