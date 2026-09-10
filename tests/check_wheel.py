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
    "maniml/web/generated_geometry.py",
    "maniml/web/triangle_scene.py",
    "maniml/web/triangle_geometry.py",
    # The installed app's identity: without these the engine serves a page
    # that cannot be installed, and the icon and offline shell disappear.
    "maniml/web/static/manifest.webmanifest",
    "maniml/web/static/sw.js",
    "maniml/web/static/icons/maniml-192.png",
    "maniml/web/static/icons/maniml-512.png",
    "maniml/utils/safe_text_cache.py",
}
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
            raise SystemExit(f"wheel contains retired WebGL2 assets: {retired[:5]}")
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
    for required in ("audioop-lts", "pydub", "websockets"):
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


if __name__ == "__main__":
    load_native = "--load-native" in sys.argv[1:]
    patterns = [argument for argument in sys.argv[1:] if argument != "--load-native"]
    candidates = [Path(path) for pattern in patterns for path in glob(pattern)]
    if not patterns:
        candidates = list(Path("dist").glob("*.whl"))
    if len(candidates) != 1:
        raise SystemExit("expected exactly one wheel: check_wheel.py [--load-native] [PATH_TO_WHEEL]")
    check_wheel(candidates[0])
    if load_native:
        check_native_loader(candidates[0])
    print(f"wheel contents OK: {candidates[0]}")
