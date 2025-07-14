"""
Transform animations with CE compatibility.
"""

import manim
from manim.animation.transform import (
    Transform as GLTransform,
    ReplacementTransform as GLReplacementTransform,
)
import warnings

# Try to import others that might not exist
try:
    from manim.animation.transform import TransformFromCopy as GLTransformFromCopy
except ImportError:
    GLTransformFromCopy = None

try:
    from manim.animation.transform import MoveToTarget as GLMoveToTarget
except ImportError:
    GLMoveToTarget = None

try:
    from manim.animation.transform import ApplyMethod as GLApplyMethod
except ImportError:
    GLApplyMethod = None

try:
    from manim.animation.transform import ApplyPointwiseFunction as GLApplyPointwiseFunction
except ImportError:
    GLApplyPointwiseFunction = None

try:
    from manim.animation.transform import ApplyMatrix as GLApplyMatrix
except ImportError:
    GLApplyMatrix = None


# Direct mappings
Transform = GLTransform
ReplacementTransform = GLReplacementTransform

# MoveToTarget if available
if GLMoveToTarget:
    MoveToTarget = GLMoveToTarget
else:
    class MoveToTarget(GLTransform):
        """CE-compatible MoveToTarget."""
        def __init__(self, mobject, **kwargs):
            if hasattr(mobject, 'target'):
                super().__init__(mobject, mobject.target, **kwargs)
            else:
                warnings.warn("maniml: MoveToTarget requires mobject.target to be set", UserWarning)
                super().__init__(mobject, mobject.copy(), **kwargs)

# ApplyMethod if available
if GLApplyMethod:
    ApplyMethod = GLApplyMethod
else:
    class ApplyMethod(GLTransform):
        """Simplified ApplyMethod."""
        def __init__(self, method, *args, **kwargs):
            warnings.warn("maniml: ApplyMethod simplified", UserWarning)
            mobject = method.__self__
            # Apply the method to a copy to get target state
            target = mobject.copy()
            method_name = method.__name__
            getattr(target, method_name)(*args)
            super().__init__(mobject, target, **kwargs)

# ApplyPointwiseFunction if available
if GLApplyPointwiseFunction:
    ApplyPointwiseFunction = GLApplyPointwiseFunction
else:
    ApplyPointwiseFunction = GLTransform  # Fallback

# ApplyMatrix if available
if GLApplyMatrix:
    ApplyMatrix = GLApplyMatrix
else:
    class ApplyMatrix(GLTransform):
        """Simplified ApplyMatrix."""
        def __init__(self, matrix, mobject, **kwargs):
            warnings.warn("maniml: ApplyMatrix simplified", UserWarning)
            target = mobject.copy()
            # Apply matrix transformation
            import numpy as np
            if hasattr(target, 'apply_matrix'):
                target.apply_matrix(matrix)
            super().__init__(mobject, target, **kwargs)


# ClockwiseTransform - these don't exist in GL, create simple versions
class ClockwiseTransform(GLTransform):
    """CE-compatible ClockwiseTransform - simplified to regular transform."""
    def __init__(self, mobject, target, **kwargs):
        warnings.warn("maniml: ClockwiseTransform simplified to Transform", UserWarning)
        kwargs['path_arc'] = -90 * manimlib.constants.DEGREES
        super().__init__(mobject, target, **kwargs)


class CounterclockwiseTransform(GLTransform):
    """CE-compatible CounterclockwiseTransform - simplified to regular transform."""
    def __init__(self, mobject, target, **kwargs):
        warnings.warn("maniml: CounterclockwiseTransform simplified to Transform", UserWarning)
        kwargs['path_arc'] = 90 * manimlib.constants.DEGREES
        super().__init__(mobject, target, **kwargs)


# TransformFromCopy
if GLTransformFromCopy:
    TransformFromCopy = GLTransformFromCopy
else:
    class TransformFromCopy(GLTransform):
        """CE-compatible TransformFromCopy - transform from a copy of source."""
        
        def __init__(self, source, target, **kwargs):
            # Create a copy of source
            source_copy = source.copy()
            super().__init__(source_copy, target, **kwargs)
            
            # Store reference to original
            self.source_original = source
            self.source_copy = source_copy
        
        def begin(self):
            # Add the copy to the scene
            self.mobject.get_family()[0].add(self.source_copy)
            super().begin()


class Swap(GLTransform):
    """CE-compatible Swap - swap two mobjects."""
    
    def __init__(self, mobject1, mobject2, **kwargs):
        # Create transforms in both directions
        self.transform1 = Transform(mobject1.copy(), mobject2, **kwargs)
        self.transform2 = Transform(mobject2.copy(), mobject1, **kwargs)
        
        # Use AnimationGroup
        from manim.animation.composition import AnimationGroup
        self.anim_group = AnimationGroup(self.transform1, self.transform2)
        
        # Inherit from first transform
        super().__init__(mobject1, mobject2, **kwargs)


class Restore(GLTransform):
    """CE-compatible Restore - restore mobject to saved state."""
    
    def __init__(self, mobject, **kwargs):
        if hasattr(mobject, 'saved_state'):
            super().__init__(mobject, mobject.saved_state, **kwargs)
        else:
            warnings.warn(
                "maniml: No saved state found. Use mobject.save_state() first.",
                UserWarning
            )
            # No-op transform
            super().__init__(mobject, mobject.copy(), **kwargs)


class TransformMatchingShapes(GLTransform):
    """CE-compatible TransformMatchingShapes - simplified version."""
    
    def __init__(self, source, target, transform_mismatches=True, **kwargs):
        warnings.warn(
            "maniml: TransformMatchingShapes simplified to regular Transform.",
            UserWarning
        )
        super().__init__(source, target, **kwargs)


class TransformMatchingTex(GLTransform):
    """CE-compatible TransformMatchingTex - transform matching TeX parts."""
    
    def __init__(self, source, target, key_map=None, transform_mismatches=True, **kwargs):
        warnings.warn(
            "maniml: TransformMatchingTex simplified to regular Transform. "
            "Use multiple transforms for complex TeX matching.",
            UserWarning
        )
        
        # Simplified version - just transform the whole thing
        super().__init__(source, target, **kwargs)
        
        # Could be enhanced to actually match TeX strings if needed