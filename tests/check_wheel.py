"""Validate the contents and core metadata of a built maniml wheel."""

from __future__ import annotations

import sys
import os
import subprocess
from email.parser import Parser
from glob import glob
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

# The frontend ships inside the wheel: that is what makes engine/UI skew
# impossible, so a wheel missing any of it is broken rather than merely thin.
REQUIRED_ASSETS = {
    "maniml/web/static/app.html",
    "maniml/web/static/shell.css",
    "maniml/web/static/viewer.html",
    "maniml/web/static/player.html",
    "maniml/web/static/player.js",
    "maniml/web/static/geometry_recording.js",
    "maniml/web/static/webgpu.js",
    "maniml/web/static/winding_webgpu.js",
    "maniml/web/static/renderer_selection.js",
    "maniml/web/winding_geometry.py",
    "maniml/web/border_geometry.py",
    "maniml/web/fill_paint.py",
    "maniml/web/static/wgsl/paint.wgsl",
    "maniml/web/static/wgsl/border_compute.wgsl",
    "maniml/web/gpu_border_geometry.py",
    "maniml/web/static/wgsl/resolve2.wgsl",
    "maniml/web/generated_geometry.py",
    "maniml/web/triangle_scene.py",
    "maniml/web/triangle_geometry.py",
    "maniml/web/wgpu_renderer.py",
    "maniml/camera/native_gl_camera.py",
    "maniml/rendering/shader_wrapper.py",
    "maniml/rendering/gl_shaders.py",
    # The installed app's identity: without these the engine serves a page
    # that cannot be installed, and the icon and offline shell disappear.
    "maniml/web/static/manifest.webmanifest",
    "maniml/web/static/sw.js",
    "maniml/web/static/icons/maniml-192.png",
    "maniml/web/static/icons/maniml-512.png",
    "maniml/utils/safe_text_cache.py",
}
REQUIRED_ASSETS.update(
    f"maniml/web/static/winding_wgsl/{name}.wgsl"
    for name in ("common", "fill", "blit", "composite", "stroke",
                 "surface", "image", "texsurface", "dot")
)
REQUIRED_ASSETS.update(
    f"maniml/rendering/shaders/{folder}/{stage}.glsl"
    for folder, stages in (
        ("image", ("vert", "frag")),
        ("surface", ("vert", "frag")),
        ("textured_surface", ("vert", "frag")),
        ("true_dot", ("vert", "geom", "frag")),
        ("mandelbrot_fractal", ("vert", "frag")),
        ("newton_fractal", ("vert", "frag")),
        ("quadratic_bezier/fill", ("vert", "geom", "frag")),
        ("quadratic_bezier/stroke", ("vert", "geom", "frag")),
        ("quadratic_bezier/depth", ("vert", "geom", "frag")),
    )
    for stage in stages
)
REQUIRED_ASSETS.update(
    f"maniml/rendering/shaders/{name}.glsl"
    for name in ("simple_vert", "inserts/get_xyz_to_uv", "inserts/get_unit_normal",
                 "inserts/finalize_color", "inserts/complex_functions",
                 "inserts/emit_gl_Position")
)
REQUIRED_LICENSES = {"LICENSE", "LICENSE.community", "THIRD_PARTY_LICENSES.txt",
                     "RUST_STANDARD_LIBRARY_LICENSES.html"}
RETIRED_ASSETS = {"maniml/web/static/gl.js"}
RETIRED_PREFIXES = ("maniml/web/static/glsl/",)


def check_wheel(path: Path) -> None:
    if path.suffix != ".whl" or not path.is_file():
        raise SystemExit(f"not a wheel: {path}")

    with ZipFile(path) as wheel:
        names = set(wheel.namelist())
        missing = sorted(REQUIRED_ASSETS - names)
        if missing:
            raise SystemExit(f"wheel is missing packaged assets: {missing}")
        native_helpers = [name for name in names
                          if name.startswith("maniml/web/maniml_lyon_fill")
                          and name.endswith((".so", ".pyd", ".dylib"))]
        if len(native_helpers) != 1:
            raise SystemExit("wheel must contain exactly one packaged Lyon helper")
        retired = sorted(
            name for name in names
            if name in RETIRED_ASSETS or name.startswith(RETIRED_PREFIXES)
        )
        if retired:
            raise SystemExit(f"wheel contains retired GL assets: {retired[:5]}")
        leaked = sorted(
            name for name in names if name.startswith(("tests/", "example_scenes/"))
        )
        if leaked:
            raise SystemExit(f"wheel contains development files: {leaked[:5]}")
        licenses = {Path(name).name for name in names if ".dist-info/licenses/" in name}
        missing_licenses = sorted(REQUIRED_LICENSES - licenses)
        if missing_licenses:
            raise SystemExit(f"wheel is missing license notices: {missing_licenses}")
        metadata_names = [
            name for name in names if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise SystemExit("wheel must contain exactly one METADATA file")
        metadata = Parser().parsestr(wheel.read(metadata_names[0]).decode("utf-8"))

    if metadata["Name"] != "maniml":
        raise SystemExit(f"unexpected package name: {metadata['Name']}")
    if metadata["Requires-Python"] != ">=3.11":
        raise SystemExit(
            f"unexpected Python requirement: {metadata['Requires-Python']}"
        )
    if metadata.get_all("Provides-Extra") != ["webgpu"]:
        raise SystemExit(
            f"unexpected public extras: {metadata.get_all('Provides-Extra')}"
        )

    dependencies = [value.lower() for value in metadata.get_all("Requires-Dist", [])]
    for required in ("audioop-lts", "pydub", "websockets", "wgpu", "moderngl", "pyopengl"):
        if not any(value.startswith(required) for value in dependencies):
            raise SystemExit(f"wheel is missing dependency metadata for {required}")
    if any(value.startswith("diskcache") for value in dependencies):
        raise SystemExit("wheel still depends on unsafe pickle cache diskcache")


def check_native_loader(path: Path) -> None:
    """Run the extracted adapter/helper, never this checkout or an env override.

    This optional smoke test requires a wheel built for the executing host and
    NumPy in the interpreter's environment. It performs no install or rebuild.
    """
    with TemporaryDirectory(prefix="maniml-wheel-native-") as directory:
        with ZipFile(path) as wheel:
            for name in wheel.namelist():
                if name == "maniml/web/triangle_geometry.py" or (
                    name.startswith("maniml/web/maniml_lyon_fill")
                    and name.endswith((".so", ".pyd", ".dylib"))
                ):
                    wheel.extract(name, directory)
        module = Path(directory) / "maniml/web/triangle_geometry.py"
        # -I removes cwd/PYTHONPATH imports. Loading this single module by its
        # extracted filename also avoids the installed maniml package entirely.
        program = r'''
import importlib.util
import pathlib
import sys
import numpy as np
spec = importlib.util.spec_from_file_location("wheel_triangle_geometry", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
tessellator = module.LyonFillTessellator()
assert pathlib.Path(tessellator.library_path).parent == pathlib.Path(sys.argv[1]).resolve().parent
points = np.array([[0,0],[2,0],[4,0],[4,2],[4,4],[2,4],[0,4],[0,2],[0,0]], dtype=float)
points.flags.writeable = False
for width, expected in ((0,16), (1,24.5)):
    mesh = tessellator.tessellate([points], border_width=width)
    triangles = mesh.positions[mesh.indices.reshape(-1,3)].astype(float)
    ab = triangles[:,1] - triangles[:,0]
    ac = triangles[:,2] - triangles[:,0]
    area = np.abs(ab[:,0] * ac[:,1] - ab[:,1] * ac[:,0]).sum() / 2
    assert abs(area - expected) < 1e-5, (area,expected)
print("extracted packaged Lyon loader: fill and border OK")
'''
        environment = os.environ.copy()
        environment.pop("MANIML_LYON_LIBRARY", None)
        subprocess.run([sys.executable, "-I", "-c", program, str(module)],
                       cwd=directory, env=environment, check=True)


def check_native_gl(path: Path) -> None:
    """Capture with packaged GL from an extracted wheel, with tests unavailable."""
    with TemporaryDirectory(prefix="maniml-wheel-gl-") as directory:
        with ZipFile(path) as wheel:
            wheel.extractall(directory)
        program = r'''
import importlib.abc
import pathlib
import sys
import numpy as np
root = pathlib.Path(sys.argv[1]).resolve()
class RejectTests(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "tests" or fullname.startswith("tests."):
            raise AssertionError("packaged GL must not import tests: " + fullname)
sys.meta_path.insert(0, RejectTests())
sys.path.insert(0, str(root))
import maniml
from maniml import Camera, NativeGLCamera, Scene, ShaderWrapper, Square
from maniml.rendering.shader_wrapper import ShaderWrapper as RealShaderWrapper
assert pathlib.Path(maniml.__file__).resolve().is_relative_to(root)
assert ShaderWrapper is RealShaderWrapper
assert Scene.camera_class is Camera
camera = NativeGLCamera(resolution=(96, 64))
try:
    camera.capture(Square(fill_color="#FF0000", fill_opacity=1, stroke_width=0))
    image = np.asarray(camera.get_image())
    assert image.shape == (64, 96, 4), image.shape
    np.testing.assert_allclose(image[32, 48], [255, 0, 0, 255], atol=1)
    np.testing.assert_array_equal(image[0, 0], [0, 0, 0, 255])
finally:
    camera.release()
assert not any(name == "tests" or name.startswith("tests.") for name in sys.modules)
print("extracted packaged native GL: capture OK; Phase A remains default")
'''
        environment = os.environ.copy()
        environment.pop("MANIML_LYON_LIBRARY", None)
        subprocess.run([sys.executable, "-I", "-c", program, directory],
                       cwd=directory, env=environment, check=True)


def check_native_wgpu(path: Path) -> None:
    """Exercise the extracted default Camera and packaged GPU border kernel.

    The CPU-border comparison uses the same installed public capture API with
    its explicit diagnostic selector. Neither path can import checkout tests,
    benchmark helpers, an editable maniml, or an external Lyon override.
    """
    with TemporaryDirectory(prefix="maniml-wheel-wgpu-") as directory:
        with ZipFile(path) as wheel:
            wheel.extractall(directory)
        program = r'''
import importlib.abc
import os
import pathlib
import sys
import numpy as np
root = pathlib.Path(sys.argv[1]).resolve()
class RejectDevelopmentImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in ("tests", "benchmarks"):
            raise AssertionError("wheel capture imported development code: " + fullname)
sys.meta_path.insert(0, RejectDevelopmentImports())
sys.path.insert(0, str(root))
import maniml
from maniml import Camera, Circle, Scene
from maniml.web import gpu_border_geometry, wgpu_renderer
assert pathlib.Path(maniml.__file__).resolve().is_relative_to(root)
assert pathlib.Path(gpu_border_geometry.__file__).resolve().is_relative_to(root)
assert pathlib.Path(wgpu_renderer.__file__).resolve().is_relative_to(root)
assert Scene.camera_class is Camera
assert "MANIML_BORDER_GENERATOR" not in os.environ
assert "MANIML_LYON_LIBRARY" not in os.environ
shape = Circle(radius=.9, fill_color="#FF0000", fill_opacity=.5,
               fill_border_width=48, stroke_width=0)
fields = ("point", "fill_rgba", "fill_border_width", "stroke_rgba", "stroke_width")
source = [shape.data[name].tobytes() for name in fields]
gpu = Camera(resolution=(256, 144), background_opacity=0)
cpu = Camera(resolution=(256, 144), background_opacity=0)
try:
    gpu.capture(shape)
    pixels = np.asarray(gpu.get_image())
    assert pixels.shape == (144, 256, 4), pixels.shape
    assert gpu._geometry_cache.border_generator == "gpu"
    assert gpu._renderer._border_sources and gpu._renderer._border_outputs
    assert "border_compute" in gpu._renderer._modules
    helper = pathlib.Path(gpu._geometry_cache.triangle_tessellator.library_path).resolve()
    assert helper.parent == root / "maniml/web", helper
    np.testing.assert_allclose(pixels[72, 128], [255, 0, 0, 128], rtol=0, atol=1)
    np.testing.assert_array_equal(pixels[0, 0], [0, 0, 0, 0])
    os.environ["MANIML_BORDER_GENERATOR"] = "cpu"
    cpu.capture(shape)
    reference = np.asarray(cpu.get_image())
    assert cpu._geometry_cache.border_generator == "cpu"
    assert not cpu._renderer._border_sources and not cpu._renderer._border_outputs
    np.testing.assert_allclose(pixels, reference, rtol=0, atol=1)
    assert [shape.data[name].tobytes() for name in fields] == source
    # Prove the default route emitted visible border coverage, rather than
    # merely uploading/dispatching an unused source buffer.
    os.environ.pop("MANIML_BORDER_GENERATOR")
    no_border = shape.copy().set_fill(border_width=0)
    gpu.capture(no_border)
    interior = np.asarray(gpu.get_image())
    added_coverage = pixels[..., 3].astype(int) - interior[..., 3].astype(int)
    assert np.count_nonzero(added_coverage > 16) > 20, added_coverage.max()
    assert not gpu._renderer._border_sources and not gpu._renderer._border_outputs
    assert [shape.data[name].tobytes() for name in fields] == source
finally:
    gpu.release()
    cpu.release()
assert not any(name.split(".")[0] in ("tests", "benchmarks") for name in sys.modules)
maximum = np.abs(pixels.astype(int) - reference.astype(int)).max()
print(f"extracted packaged default WebGPU: GPU borders/straight alpha/source retention OK; CPU reference max RGBA difference {maximum}")
'''
        environment = os.environ.copy()
        for name in ("MANIML_LYON_LIBRARY", "MANIML_BORDER_GENERATOR", "MANIML_RENDERER"):
            environment.pop(name, None)
        subprocess.run([sys.executable, "-I", "-c", program, directory],
                       cwd=directory, env=environment, check=True)


if __name__ == "__main__":
    load_native = "--load-native" in sys.argv[1:]
    load_gl = "--load-gl" in sys.argv[1:]
    load_wgpu = "--load-wgpu" in sys.argv[1:]
    patterns = [argument for argument in sys.argv[1:]
                if argument not in ("--load-native", "--load-gl", "--load-wgpu")]
    candidates = [Path(path) for pattern in patterns for path in glob(pattern)]
    if not patterns:
        candidates = list(Path("dist").glob("*.whl"))
    if len(candidates) != 1:
        raise SystemExit("expected exactly one wheel: check_wheel.py [--load-native] [--load-gl] [--load-wgpu] [PATH_TO_WHEEL]")
    check_wheel(candidates[0])
    if load_native:
        check_native_loader(candidates[0])
    if load_gl:
        check_native_gl(candidates[0])
    if load_wgpu:
        check_native_wgpu(candidates[0])
    print(f"wheel contents OK: {candidates[0]}")
