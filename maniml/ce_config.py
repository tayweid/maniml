"""CE-compatible `config` object.

Current ManimCE configures scenes through module-level assignments like

    config.background_color = WHITE
    config.pixel_width = 2160
    config.frame_rate = 30

maniml's scene modules execute before the Scene/Camera are created, so
these map cleanly onto manim_config (which Scene merges at creation
time). Supported settings take effect; unsupported ones warn loudly
instead of failing silently.
"""
from __future__ import annotations

from maniml.config import manim_config
from maniml.logger import log


class CEConfig:
    def __init__(self):
        object.__setattr__(self, "_warned", set())

    # Supported settings, mapped onto manim_config

    @property
    def background_color(self):
        return manim_config.camera.background_color

    @background_color.setter
    def background_color(self, value):
        manim_config.camera.background_color = str(value)

    @property
    def pixel_width(self) -> int:
        return manim_config.camera.resolution[0]

    @pixel_width.setter
    def pixel_width(self, value):
        resolution = manim_config.camera.resolution
        manim_config.camera.resolution = (int(value), resolution[1])

    @property
    def pixel_height(self) -> int:
        return manim_config.camera.resolution[1]

    @pixel_height.setter
    def pixel_height(self, value):
        resolution = manim_config.camera.resolution
        manim_config.camera.resolution = (resolution[0], int(value))

    @property
    def frame_rate(self) -> float:
        return manim_config.camera.fps

    @frame_rate.setter
    def frame_rate(self, value):
        manim_config.camera.fps = value

    # Everything else: loud, not silent

    def __setattr__(self, name, value):
        prop = getattr(type(self), name, None)
        if isinstance(prop, property) and prop.fset is not None:
            prop.fset(self, value)
            return
        if name not in self._warned:
            self._warned.add(name)
            log.warning(
                f"config.{name} is not supported by maniml; "
                "the assignment was ignored"
            )

    def __getattr__(self, name):
        # Fall through to the GL config module so existing access such
        # as manim.config.manim_config keeps working. Resolved through
        # sys.modules: the `manim.config` attribute on the package is
        # this shim itself.
        import sys
        _config_module = sys.modules['maniml.config']
        try:
            return getattr(_config_module, name)
        except AttributeError:
            raise AttributeError(f"config has no setting {name!r}") from None

    # CE also allows dict-style access

    def __getitem__(self, name):
        return getattr(self, name)

    def __setitem__(self, name, value):
        setattr(self, name, value)


config = CEConfig()
