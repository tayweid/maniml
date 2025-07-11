"""Boolean operations for two-dimensional mobjects."""

from __future__ import annotations

__all__ = ["Union", "Intersection", "Difference", "Exclusion"]

from typing import TYPE_CHECKING, Any
import warnings

from manim.renderer.opengl.mobject.types.vectorized_mobject import VMobject

if TYPE_CHECKING:
    pass


class _BooleanOpsPlaceholder(VMobject):
    """Placeholder for boolean operations until pathops is fixed."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        warnings.warn(
            "Boolean operations are not yet implemented in maniml. "
            "This is a placeholder that returns an empty shape.",
            UserWarning
        )


class Union(_BooleanOpsPlaceholder):
    """Union of two or more :class:`~.VMobject` s."""
    def __init__(self, *vmobjects: VMobject, **kwargs: Any) -> None:
        if len(vmobjects) < 2:
            raise ValueError("At least 2 mobjects needed for Union.")
        super().__init__(**kwargs)


class Difference(_BooleanOpsPlaceholder):
    """Subtracts one :class:`~.VMobject` from another one."""
    def __init__(self, subject: VMobject, clip: VMobject, **kwargs: Any) -> None:
        super().__init__(**kwargs)


class Intersection(_BooleanOpsPlaceholder):
    """Find the intersection of two :class:`~.VMobject` s."""
    def __init__(self, *vmobjects: VMobject, **kwargs: Any) -> None:
        if len(vmobjects) < 2:
            raise ValueError("At least 2 mobjects needed for Intersection.")
        super().__init__(**kwargs)


class Exclusion(_BooleanOpsPlaceholder):
    """Find the XOR between two :class:`~.VMobject`."""
    def __init__(self, subject: VMobject, clip: VMobject, **kwargs: Any) -> None:
        super().__init__(**kwargs)