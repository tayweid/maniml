"""Validate the contents and core metadata of a built maniml wheel."""

from __future__ import annotations

import sys
from email.parser import Parser
from glob import glob
from pathlib import Path
from zipfile import ZipFile

# The frontend ships inside the wheel: that is what makes engine/UI skew
# impossible, so a wheel missing any of it is broken rather than merely thin.
REQUIRED_ASSETS = {
    "maniml/web/static/app.html",
    "maniml/web/static/viewer.html",
    "maniml/web/static/player.html",
    "maniml/web/static/player.js",
    "maniml/web/static/gl.js",
    "maniml/web/static/webgpu.js",
    "maniml/web/static/icons/maniml-192.png",
    "maniml/web/static/icons/maniml-512.png",
    "maniml/utils/safe_text_cache.py",
}
REQUIRED_LICENSES = {"LICENSE", "LICENSE.community"}


def check_wheel(path: Path) -> None:
    if path.suffix != ".whl" or not path.is_file():
        raise SystemExit(f"not a wheel: {path}")

    with ZipFile(path) as wheel:
        names = set(wheel.namelist())
        missing = sorted(REQUIRED_ASSETS - names)
        if missing:
            raise SystemExit(f"wheel is missing packaged assets: {missing}")
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


if __name__ == "__main__":
    candidates = [Path(path) for pattern in sys.argv[1:] for path in glob(pattern)]
    if not sys.argv[1:]:
        candidates = list(Path("dist").glob("*.whl"))
    if len(candidates) != 1:
        raise SystemExit("expected exactly one wheel: check_wheel.py [PATH_TO_WHEEL]")
    check_wheel(candidates[0])
    print(f"wheel contents OK: {candidates[0]}")
