"""Function scenes: a scene written as a decorated function, without a class.

    @Scene
    def Intro():
        circle = Circle()
        play(Create(circle))
        pause()

A file can hold several, side by side. The scene class is the decorator.
``Scene(fn)`` (and ``ThreeDScene(fn)``, or any subclass) returns a real
subclass named after the function, so everything that finds, names and
runs a scene class finds this one: the CLI's discovery, the source map
(which reads the function's body as it reads construct()'s), the
watcher, the app's scene picker. The engine never called construct() to
run a scene anyway; it executes the body's units one at a time against a
namespace, so a function body and a construct() body are the same thing
to it.

The verbs (``play``, ``wait``, ``pause``, ``add``, ...) are plain
functions that call the method of the scene that is running. They are
real functions rather than names planted in a namespace, so an editor
sees them and a helper in another module can call them.

Anything that is not a verb (the camera's frame, the scene's clock, a
method with no verb) goes through the scene itself: a function that takes
one parameter gets the scene in it, under whatever name it gives.

    @ThreeDScene
    def Orbit(s):
        add(Sphere())
        play(s.frame.animate.increment_theta(PI / 2))
"""

from __future__ import annotations

import inspect

_active = None


def activate(scene) -> None:
    """Make `scene` the one the verbs call: set as it runs, and before
    each unit it executes, so the most recent scene to do anything is the
    one a verb reaches."""
    global _active
    _active = scene


def deactivate(scene) -> None:
    """Forget `scene` once it is torn down, so a finished scene is not
    kept alive by the verbs' reference to it."""
    global _active
    if _active is scene:
        _active = None


def active_scene():
    """The scene the verbs call."""
    if _active is None:
        raise RuntimeError(
            "no scene is running: play(), add() and the other scene verbs "
            "work inside a scene, a function decorated with @Scene "
            "(or the construct() of a Scene class)")
    return _active


def is_scene_function(value) -> bool:
    """Whether `Scene(value)` means "make a scene class of this function"
    rather than "make a scene with this window": a plain function never
    is a window."""
    return inspect.isfunction(value)


def scene_class_from_function(base: type, function) -> type:
    """The `base` subclass a function scene stands for.

    It is named after the function and claims its module, so the CLI's
    `issubclass(obj, Scene) and obj.__module__ == module.__name__` finds
    it and `build_units(source, cls.__name__)` finds its body. The body's
    one optional parameter is the scene's handle (`_scene_handle`), which
    the engine binds wherever it binds `self`.
    """
    parameters = list(inspect.signature(function).parameters.values())
    positional = (inspect.Parameter.POSITIONAL_ONLY,
                  inspect.Parameter.POSITIONAL_OR_KEYWORD)
    if len(parameters) > 1 or any(p.kind not in positional for p in parameters):
        raise TypeError(
            f"{function.__name__}(), a @{base.__name__} scene, takes at most "
            f"one parameter (it is given the scene)")
    handle = parameters[0].name if parameters else None

    def construct(self):
        activate(self)
        if handle is None:
            function()
        else:
            function(self)

    construct.__qualname__ = f"{function.__qualname__}.construct"
    return type(function.__name__, (base,), {
        "__module__": function.__module__,
        "__qualname__": function.__qualname__,
        "__doc__": function.__doc__,
        "construct": construct,
        "scene_function": staticmethod(function),
        "_scene_handle": handle,
    })


# The verbs. Each is the method of the same name on the running scene, so
# a ThreeDScene's add() (which turns on depth testing) is what add() does
# in a ThreeDScene.

def play(*animations, **kwargs):
    """Scene.play on the running scene: play animations, then save a
    checkpoint."""
    return active_scene().play(*animations, **kwargs)


def wait(*args, **kwargs):
    """Scene.wait on the running scene."""
    return active_scene().wait(*args, **kwargs)


def wait_until(*args, **kwargs):
    """Scene.wait_until on the running scene."""
    return active_scene().wait_until(*args, **kwargs)


def pause(*args, **kwargs):
    """Scene.pause on the running scene: mark a pausepoint."""
    return active_scene().pause(*args, **kwargs)


def next_section(*args, **kwargs):
    """Scene.next_section on the running scene (a pausepoint)."""
    return active_scene().next_section(*args, **kwargs)


def add(*mobjects, **kwargs):
    """Scene.add on the running scene."""
    return active_scene().add(*mobjects, **kwargs)


def remove(*mobjects):
    """Scene.remove on the running scene."""
    return active_scene().remove(*mobjects)


def clear():
    """Scene.clear on the running scene."""
    return active_scene().clear()


def bring_to_front(*mobjects):
    """Scene.bring_to_front on the running scene."""
    return active_scene().bring_to_front(*mobjects)


def bring_to_back(*mobjects):
    """Scene.bring_to_back on the running scene."""
    return active_scene().bring_to_back(*mobjects)


def add_sound(*args, **kwargs):
    """Scene.add_sound on the running scene."""
    return active_scene().add_sound(*args, **kwargs)


def set_background_color(*args, **kwargs):
    """Scene.set_background_color on the running scene."""
    return active_scene().set_background_color(*args, **kwargs)


def set_camera_orientation(*args, **kwargs):
    """ThreeDScene.set_camera_orientation on the running scene."""
    return active_scene().set_camera_orientation(*args, **kwargs)


def begin_ambient_camera_rotation(*args, **kwargs):
    """ThreeDScene.begin_ambient_camera_rotation on the running scene."""
    return active_scene().begin_ambient_camera_rotation(*args, **kwargs)


def stop_ambient_camera_rotation(*args, **kwargs):
    """ThreeDScene.stop_ambient_camera_rotation on the running scene."""
    return active_scene().stop_ambient_camera_rotation(*args, **kwargs)


VERBS = (
    "play", "wait", "wait_until", "pause", "next_section",
    "add", "remove", "clear", "bring_to_front", "bring_to_back",
    "add_sound", "set_background_color",
    "set_camera_orientation", "begin_ambient_camera_rotation",
    "stop_ambient_camera_rotation",
)
