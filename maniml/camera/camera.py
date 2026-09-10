from __future__ import annotations

import numpy as np
from PIL import Image
from types import SimpleNamespace

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
    from typing import Optional
    from maniml.typing import ManimColor, Vect3


class Camera(object):
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
        # Retained compatibility metadata. Phase A selects its shared quality
        # policy independently; the Original 2D viewer still uses this value.
        samples: int = 0,
    ):
        self.background_image = background_image
        self.default_pixel_shape = resolution  # Rename?
        self.fps = fps
        self.max_allowable_norm = max_allowable_norm
        self.image_mode = image_mode
        if (isinstance(n_channels, bool) or not isinstance(n_channels, (int, np.integer))
                or not 1 <= n_channels <= 4):
            raise ValueError("camera n_channels must be an integer from 1 to 4")
        self.n_channels = int(n_channels)
        self.pixel_array_dtype = pixel_array_dtype
        self.light_source_position = light_source_position
        self.samples = samples

        self.rgb_max_val: float = np.iinfo(self.pixel_array_dtype).max
        self.background_rgba: list[float] = list(color_to_rgba(
            background_color, background_opacity
        ))
        self.uniforms = dict()
        # GPU resources and generated meshes are derived capture state, not
        # scene/checkpoint data. Browser-only scenes never initialize them.
        self._renderer = None
        self._geometry_cache = None
        self._image = None
        self.init_frame(**frame_config)
        self.init_fbo()
        self.init_light_source()

    def init_frame(self, **config) -> None:
        self.frame = CameraFrame(**config)

    def init_fbo(self) -> None:
        # Keep the size metadata consumed by the shared geometry encoder.
        # Actual textures belong exclusively to the lazy native driver.
        size = tuple(self.default_pixel_shape)
        if len(size) != 2 or any(int(value) != value or value <= 0 for value in size):
            raise ValueError("camera resolution must contain two positive integers")
        self.fbo = self.draw_fbo = SimpleNamespace(size=tuple(map(int, size)))
        self.clear()

    def init_light_source(self) -> None:
        self.light_source = Point(self.light_source_position)

    def clear(self) -> None:
        rgba = tuple(np.clip(np.rint(255 * np.asarray(self.background_rgba)), 0, 255).astype(int))
        self._image = Image.new("RGBA", self.get_pixel_shape(), rgba)

    def get_raw_fbo_data(self, dtype: str = 'f1') -> bytes:
        """Configured color channels, bottom first, preserving the byte API.

        The default is straight RGBA. FFmpeg applies its existing vflip once.
        Images and pixel-array reads use normal top-first order; requesting
        fewer channels selects the leading R, RG, or RGB components.
        """
        data = np.asarray(self._current_image())[::-1, :, :self.n_channels]
        if dtype == 'f1':
            return data.tobytes()
        if dtype == 'f4':
            return (data.astype(np.float32) / 255).tobytes()
        raise ValueError("camera pixel bytes support 'f1' or 'f4'")

    def _current_image(self) -> Image.Image:
        if self._image is None or self._image.size != self.get_pixel_shape():
            self.clear()
        return self._image

    def get_image(self) -> Image.Image:
        return self._current_image().copy()

    def get_pixel_array(self) -> np.ndarray:
        data = np.asarray(self._current_image())[..., :self.n_channels]
        if self.pixel_array_dtype == np.uint8:
            return data.copy()
        return np.rint(data.astype(np.float64) * (self.rgb_max_val / 255)).astype(self.pixel_array_dtype)

    def read_pixel(self, x: int, y: int) -> tuple[int, int, int, int]:
        """Read one straight-alpha RGBA pixel using a top-left origin."""
        return self._current_image().getpixel((x, y))

    def release(self) -> None:
        """Release native capture resources; a later capture starts fresh."""
        renderer = self._renderer
        self._renderer = None
        self._geometry_cache = None
        if renderer is not None:
            renderer.close()

    def __getstate__(self):
        state = self.__dict__.copy()
        state.update(_renderer=None, _geometry_cache=None, _image=None)
        return state

    # Getting camera attributes
    def get_pixel_size(self) -> float:
        return self.frame.get_width() / self.get_pixel_shape()[0]

    def get_pixel_shape(self) -> tuple[int, int]:
        return self.draw_fbo.size

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
        from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
        from maniml.web.wgpu_renderer import WgpuRenderer

        if self._renderer is None:
            self._renderer = WgpuRenderer()
            self._geometry_cache = GeometryCache()
        # Use the exact same generated operations as the browser and exports.
        # Shared triangle preparation puts fixed-frame groups last for both
        # hosts. Original 2D keeps the scene's historical browser z/add order.
        scene = SimpleNamespace(camera=self, render_groups=list(mobjects))
        try:
            message = serialize_scene(scene, self._geometry_cache, renderer="triangles")
            image = self._renderer.render(*parse_geometry_message(message))
            if image.size != self.get_pixel_shape():
                raise RuntimeError("native renderer returned an unexpected image size")
        except Exception:
            # Serialization may already have advanced transport knowledge. A
            # failed submission must not turn a retry into a cache-only packet.
            self._geometry_cache.reset()
            raise
        self._image = _straight_rgba(image)


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
class ThreeDCamera(Camera):
    def __init__(self, samples: int = 4, **kwargs):
        super().__init__(samples=samples, **kwargs)


def _straight_rgba(image: Image.Image) -> Image.Image:
    """Convert the driver's premultiplied storage once at the image boundary."""
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    data = np.asarray(image)
    # Opaque movies already have straight RGB. Avoid several full-frame
    # arithmetic arrays for the overwhelmingly common opaque background case.
    if np.all(data[..., 3] == 255):
        return image
    data = data.copy()
    alpha = data[..., 3:4].astype(np.uint16)
    rgb = data[..., :3].astype(np.uint16)
    data[..., :3] = np.minimum(
        (rgb * 255 + alpha // 2) // np.maximum(alpha, 1), 255,
    ).astype(np.uint8)
    data[..., :3][alpha[..., 0] == 0] = 0
    return Image.fromarray(data, "RGBA")
