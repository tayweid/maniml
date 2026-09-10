"""Packaged native OpenGL reference renderer.

Set ``Scene.camera_class = NativeGLCamera`` to capture with the historical
renderer. The shared WebGPU camera remains the default. GL resources belong
to this camera, never to source mobjects or their checkpoint copies.
"""

from __future__ import annotations

from copy import deepcopy

from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.utils.family_ops import assemble_draw_batches
import numpy as np
from PIL import Image

from maniml.camera.camera_frame import CameraFrame
from maniml.constants import BLACK
from maniml.constants import DEFAULT_RESOLUTION
from maniml.constants import FRAME_HEIGHT
from maniml.constants import FRAME_WIDTH
from maniml.mobject.mobject import Mobject
from maniml.mobject.mobject import Point
from maniml.utils.color import color_to_rgba

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import moderngl
    from typing import Optional
    from maniml.typing import ManimColor, Vect3


class NativeGLCamera:
    def __init__(
        self,
        background_image: Optional[str] = None,
        frame_config: dict = dict(),
        # Note: frame height and width will be resized to match this resolution aspect ratio
        resolution=DEFAULT_RESOLUTION,
        fps: int = 30,
        background_color: ManimColor = BLACK,
        background_opacity: float = 1.0,
        # Points in vectorized mobjects with norm greater
        # than this value will be rescaled.
        max_allowable_norm: float = FRAME_WIDTH,
        image_mode: str = "RGBA",
        n_channels: int = 4,
        pixel_array_dtype: type = np.uint8,
        light_source_position: Vect3 = np.array([-10, 10, 10]),
        # Although vector graphics handle antialiasing fine
        # without multisampling, for 3d scenes one might want
        # to set samples to be greater than 0.
        samples: int = 0,
    ):
        self.background_image = background_image
        self.default_pixel_shape = resolution  # Rename?
        self.fps = fps
        self.max_allowable_norm = max_allowable_norm
        self.image_mode = image_mode
        self.n_channels = n_channels
        self.pixel_array_dtype = pixel_array_dtype
        self.light_source_position = light_source_position
        self.samples = samples

        self.rgb_max_val: float = np.iinfo(self.pixel_array_dtype).max
        self.background_rgba: list[float] = list(color_to_rgba(
            background_color, background_opacity
        ))
        self.uniforms = dict()
        self._wrappers = {}
        self._released = False
        self.init_frame(**frame_config)
        self.init_context()
        self.init_fbo()
        self.init_light_source()

    def init_frame(self, **config) -> None:
        self.frame = CameraFrame(**config)

    def init_context(self) -> None:
        import moderngl

        # Always a standalone (windowless) context: the live viewer draws
        # in the browser from the geometry stream, and offline output
        # reads this context's framebuffer back.
        self.ctx: moderngl.Context = moderngl.create_standalone_context()

        self.ctx.enable(moderngl.PROGRAM_POINT_SIZE)
        self.ctx.enable(moderngl.BLEND)

    def init_fbo(self) -> None:
        # This is the buffer used when writing to a video/image file
        self.fbo_for_files = self.get_fbo(self.samples)

        # This is the frame buffer we'll draw into when emitting frames
        self.draw_fbo = self.get_fbo(samples=0)

        self.fbo = self.fbo_for_files
        self.fbo.use()
        from maniml.rendering.gl_shaders import context_resources
        context_resources(self.ctx)["camera_targets"] = [
            (target, target.color_attachments, target.depth_attachment)
            for target in (self.fbo_for_files, self.draw_fbo)]

    def init_light_source(self) -> None:
        self.light_source = Point(self.light_source_position)

    def __deepcopy__(self, memo):
        """Copy source camera state and aliases; allocate GL only on capture."""
        result = type(self).__new__(type(self))
        memo[id(self)] = result
        runtime = {"ctx", "fbo", "fbo_for_files", "draw_fbo", "_wrappers", "_released"}
        for name, value in self.__dict__.items():
            if name not in runtime:
                setattr(result, name, deepcopy(value, memo))
        result.default_pixel_shape = self.get_pixel_shape()
        result.ctx = result.fbo = result.fbo_for_files = result.draw_fbo = None
        result._wrappers = {}
        result._released = False
        return result

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        wrappers = list(self._wrappers.values())
        self._wrappers.clear()
        errors = []

        def attempt(cleanup):
            try:
                cleanup()
            except Exception as error:
                errors.append(error)

        if self.ctx is not None:
            from maniml.rendering.gl_shaders import release_context_resources
            try:
                with self.ctx:
                    for _, wrapper in wrappers:
                        attempt(wrapper.release)
                    attempt(lambda: release_context_resources(self.ctx))
            except Exception as error:
                errors.append(error)
            finally:
                attempt(self.ctx.release)
        if errors:
            for error in errors[1:]:
                errors[0].add_note(f"Additional GL cleanup failure: {error}")
            raise errors[0]

    # Methods associated with the frame buffer
    def get_fbo(
        self,
        samples: int = 0
    ) -> moderngl.Framebuffer:
        return self.ctx.framebuffer(
            color_attachments=self.ctx.texture(
                self.default_pixel_shape,
                components=self.n_channels,
                samples=samples,
            ),
            depth_attachment=self.ctx.depth_renderbuffer(
                self.default_pixel_shape,
                samples=samples
            )
        )

    def clear(self) -> None:
        with self.ctx:
            self.fbo.clear(*self.background_rgba)

    def blit(self, src_fbo, dst_fbo):
        """
        Copy blocks between fbo's using Blit
        """
        import OpenGL.GL as gl

        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, src_fbo.glo)
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, dst_fbo.glo)
        gl.glBlitFramebuffer(
            *src_fbo.viewport,
            *dst_fbo.viewport,
            gl.GL_COLOR_BUFFER_BIT, gl.GL_LINEAR
        )

    def get_raw_fbo_data(self, dtype: str = 'f1') -> bytes:
        if self.fbo is None:
            raise RuntimeError("A copied NativeGLCamera must capture before reading pixels")
        with self.ctx:
            self.blit(self.fbo, self.draw_fbo)
            return self.draw_fbo.read(
                viewport=self.draw_fbo.viewport,
                components=self.n_channels,
                dtype=dtype,
            )

    def get_image(self) -> Image.Image:
        return Image.frombytes(
            'RGBA',
            self.get_pixel_shape(),
            self.get_raw_fbo_data(),
            'raw', 'RGBA', 0, -1
        )

    def get_pixel_array(self) -> np.ndarray:
        raw = self.get_raw_fbo_data(dtype='f4')
        flat_arr = np.frombuffer(raw, dtype='f4')
        arr = flat_arr.reshape([*reversed(self.draw_fbo.size), self.n_channels])
        arr = arr[::-1]
        # Convert from float
        return (self.rgb_max_val * arr).astype(self.pixel_array_dtype)

    # Needed?
    def get_texture(self) -> moderngl.Texture:
        texture = self.ctx.texture(
            size=self.fbo.size,
            components=4,
            data=self.get_raw_fbo_data(),
            dtype='f4'
        )
        return texture

    # Getting camera attributes
    def get_pixel_size(self) -> float:
        return self.frame.get_width() / self.get_pixel_shape()[0]

    def get_pixel_shape(self) -> tuple[int, int]:
        return self.default_pixel_shape if self.fbo is None else self.fbo.size

    def get_pixel_width(self) -> int:
        return self.get_pixel_shape()[0]

    def get_pixel_height(self) -> int:
        return self.get_pixel_shape()[1]

    def get_aspect_ratio(self):
        pw, ph = self.get_pixel_shape()
        return pw / ph

    def get_frame_height(self) -> float:
        return self.frame.get_height()

    def get_frame_width(self) -> float:
        return self.frame.get_width()

    def get_frame_shape(self) -> tuple[float, float]:
        return (self.get_frame_width(), self.get_frame_height())

    def get_frame_center(self) -> np.ndarray:
        return self.frame.get_center()

    def get_location(self) -> tuple[float, float, float]:
        return self.frame.get_implied_camera_location()

    def resize_frame_shape(self, fixed_dimension: bool = False) -> None:
        """
        Changes frame_shape to match the aspect ratio
        of the pixels, where fixed_dimension determines
        whether frame_height or frame_width
        remains fixed while the other changes accordingly.
        """
        frame_height = self.get_frame_height()
        frame_width = self.get_frame_width()
        aspect_ratio = self.get_aspect_ratio()
        if not fixed_dimension:
            frame_height = frame_width / aspect_ratio
        else:
            frame_width = aspect_ratio * frame_height
        self.frame.set_height(frame_height, stretch=True)
        self.frame.set_width(frame_width, stretch=True)

    # Rendering
    def capture(self, *mobjects: Mobject) -> None:
        if self._released:
            raise RuntimeError("NativeGLCamera has been released")
        if self.ctx is None:
            self.init_context()
            self.init_fbo()
        with self.ctx:
            self.fbo.clear(*self.background_rgba)
            self.refresh_uniforms()
            self.fbo.use()
            # Sort mobjects so fixed-in-frame objects render last (on top)
            sorted_mobjects = sorted(
                mobjects,
                key=lambda m: 1 if m.is_fixed_in_frame() else 0
            )
            active = set()
            for mobject in sorted_mobjects:
                family = mobject.family_members_with_points()
                active.update(family)
                wrappers = {mob: self._get_wrapper(mob) for mob in family}
                for _, members in assemble_draw_batches(family, lambda mob: wrappers[mob].get_id()):
                    wrapper = wrappers[members[0]]
                    wrapper.read_in([mob.get_shader_data() for mob in members])
                    wrapper.batch_mobjects = members
                    wrapper.update_program_uniforms(self.uniforms)
                    wrapper.pre_render()
                    wrapper.render()
            for mob in self._wrappers.keys() - active:
                _, wrapper = self._wrappers.pop(mob)
                wrapper.release()

    def _get_wrapper(self, mob):
        """Keep historical GL resources off source mobjects and checkpoints."""
        from maniml.rendering.shader_wrapper import ShaderWrapper, VShaderWrapper
        key = (mob.data.dtype, mob.shader_folder, tuple((mob.texture_paths or {}).items()),
               tuple(mob.shader_code_replacements.items()), mob.render_primitive)
        previous = self._wrappers.get(mob)
        if previous is None or previous[0] != key:
            if previous is not None:
                previous[1].release()
            kwargs = dict(ctx=self.ctx, vert_data=mob.data.copy(),
                          mobject_uniforms=mob.uniforms, depth_test=mob.depth_test,
                          code_replacements=mob.shader_code_replacements)
            if isinstance(mob, VMobject):
                wrapper = VShaderWrapper(**kwargs, stroke_behind=mob.stroke_behind)
                wrapper.mobject = mob
            else:
                wrapper = ShaderWrapper(**kwargs, shader_folder=mob.shader_folder,
                                        texture_paths=mob.texture_paths,
                                        render_primitive=mob.render_primitive)
            self._wrappers[mob] = (key, wrapper)
        else:
            wrapper = previous[1]
        wrapper.bind_to_mobject_uniforms(mob.uniforms)
        wrapper.depth_test = mob.depth_test
        if isinstance(mob, VMobject):
            wrapper.stroke_behind = mob.stroke_behind
        wrapper.refresh_id()
        return wrapper


    def refresh_uniforms(self) -> None:
        frame = self.frame
        view_matrix = frame.get_view_matrix()
        light_pos = self.light_source.get_location()
        cam_pos = self.frame.get_implied_camera_location()

        self.uniforms.update(
            view=tuple(view_matrix.T.flatten()),
            frame_scale=frame.get_scale(),
            frame_rescale_factors=(
                2.0 / FRAME_WIDTH,
                2.0 / FRAME_HEIGHT,
                frame.get_scale() / frame.get_focal_distance(),
            ),
            pixel_size=self.get_pixel_size(),
            camera_position=tuple(cam_pos),
            light_position=tuple(light_pos),
        )


# Mostly just defined so old scenes don't break
class NativeGLThreeDCamera(NativeGLCamera):
    def __init__(self, samples: int = 4, **kwargs):
        super().__init__(samples=samples, **kwargs)
