"""CPU fill-mesh adapter for the opt-in shared triangle renderer.

The input remains a list of Manim quadratic control-point contours. The output
is disposable drawing data. Coordinates are two-dimensional *tessellation*
coordinates: the caller chooses a projection/local plane and converts a pixel
error tolerance to that space. This module does not assume world xy is valid
for arbitrary 3D paths, or claim perspective/error or paint-field equivalence.

The packaged helper is discovered beside this module. A constructor path or
MANIML_LYON_LIBRARY overrides it. Importing this module does not build,
download, or load native code.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Sequence

import numpy as np


GENERATOR_ID = "lyon_tessellation-1.0.22/maniml-abi-1"
MAX_SOURCE_POINTS = 65_536
MAX_ATTRIBUTES = 32
MAX_VERTICES = 1_048_576
MAX_INDICES = 6_291_456


class TessellationError(RuntimeError):
    """A complete, valid mesh could not be generated."""


class TessellationLimitError(TessellationError):
    """The request exceeds a declared source, flattening, or output limit."""


@dataclass(frozen=True)
class FillMesh:
    positions: np.ndarray
    indices: np.ndarray
    attributes: np.ndarray
    tolerance: float
    fill_rule: str
    generator: str = GENERATOR_ID
    border_width: float = 0.0
    border_join: str | None = None
    border_miter_limit: float = 4.0

    @property
    def status(self) -> str:
        return "success" if self.indices.size else "empty"


class _MeshResult(ctypes.Structure):
    _fields_ = [
        ("vertices", ctypes.POINTER(ctypes.c_float)),
        ("vertex_floats", ctypes.c_size_t),
        ("indices", ctypes.POINTER(ctypes.c_uint32)),
        ("index_count", ctypes.c_size_t),
    ]


def _limit(value: int, maximum: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    if not 0 <= value <= maximum:
        raise TessellationLimitError(f"{name} must be between 0 and {maximum}")
    return int(value)


def _packaged_library() -> Path | None:
    """Locate setuptools-rust's NoBinding artifact, including ABI suffixes."""
    folder = Path(__file__).parent
    candidates = sorted({candidate for extension in ("so", "pyd", "dylib")
                         for candidate in folder.glob(f"maniml_lyon_fill*.{extension}")
                         if candidate.is_file()})
    if len(candidates) > 1:
        raise TessellationError("Multiple packaged Lyon helpers; select MANIML_LYON_LIBRARY explicitly")
    return candidates[0] if candidates else None


class LyonFillTessellator:
    """A reusable loader for the pinned, Python-version-independent C ABI.

    Each call has independent native tessellator state. Returned arrays own
    their storage; native allocation is released before the call returns.
    Nothing is cached using mutable source-array identity.
    """

    def __init__(self, library_path: str | os.PathLike | None = None):
        selected = library_path or os.environ.get("MANIML_LYON_LIBRARY") or _packaged_library()
        if not selected:
            raise TessellationError(
                "The packaged Lyon helper is missing. Reinstall maniml or build "
                "tools/lyon_fill and pass library_path or set MANIML_LYON_LIBRARY."
            )
        self.library_path = str(Path(selected).resolve(strict=True))
        self._library = ctypes.CDLL(self.library_path)
        self._library.ml_lyon_abi_version.argtypes = []
        self._library.ml_lyon_abi_version.restype = ctypes.c_uint32
        if self._library.ml_lyon_abi_version() != 1:
            raise TessellationError("Unsupported Lyon helper ABI; expected version 1")
        self._library.ml_lyon_tessellate.argtypes = [
            ctypes.POINTER(ctypes.c_float), ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_uint32), ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_float), ctypes.c_size_t,
            ctypes.c_float, ctypes.c_uint32,
            ctypes.c_size_t, ctypes.c_size_t,
            ctypes.POINTER(_MeshResult),
        ]
        self._library.ml_lyon_tessellate.restype = ctypes.c_uint32
        # The original ABI1 entry point remains usable with an older helper.
        # Border requests require the additive union entry point explicitly.
        self._border_function = getattr(self._library, "ml_lyon_tessellate_border", None)
        if self._border_function is not None:
            self._border_function.argtypes = [
                *self._library.ml_lyon_tessellate.argtypes[:8],
                ctypes.c_float, ctypes.c_uint32, ctypes.c_float,
                *self._library.ml_lyon_tessellate.argtypes[8:],
            ]
            self._border_function.restype = ctypes.c_uint32
        self._library.ml_lyon_free.argtypes = [ctypes.POINTER(_MeshResult)]
        self._library.ml_lyon_free.restype = None

    def tessellate(
        self,
        contours: Sequence[np.ndarray],
        *,
        attributes: Sequence[np.ndarray] | None = None,
        tolerance: float = 0.25,
        fill_rule: str = "nonzero",
        border_width: float = 0.0,
        border_join: str = "bevel",
        border_miter_limit: float = 4.0,
        max_vertices: int = 262_144,
        max_indices: int = 1_572_864,
    ) -> FillMesh:
        """Generate a complete fill, or raise without publishing a partial mesh.

        Each contour is (2*n+1, 2): anchor, handle, anchor, handle, anchor.
        Empty contours and isolated anchors are allowed; fills implicitly close
        open contours. Input arrays may be strided or read-only and are never
        modified. Nonzero is selected explicitly; evenodd is separately opt-in.

        Optional attributes are one (2*n+1, K) array per contour. Only endpoint
        rows define Lyon attributes: inserted curve vertices interpolate the
        endpoint values, and intersections combine source-edge attributes using
        Lyon's documented policy. Handle rows are deliberately unused. This is
        not a definition of a general interior gradient or arbitrary 3D surface.

        Limits cover input/output and conservative curve-subdivision work. Lyon's
        internal sweep storage is not yet governed by a hard total-memory budget.
        A tolerance of 0.25 means pixels only when the supplied space is pixels.

        A positive border_width unions the fill with a closed-path stroke in
        these same coordinates. It accepts uniform endpoint attributes only.
        Overlap has one triangle owner, including self-intersections and holes;
        painting that mesh once does not accumulate interior opacity. Bevel,
        miter (with a limit), and round are Lyon/SVG joins, not Manim's auto
        join. The binary union does not contain an antialiasing coverage band.
        ``tolerance`` controls Lyon curve flattening; it is not by itself a
        proved Hausdorff bound for every stroked cusp or miter corner.
        """
        max_vertices = _limit(max_vertices, MAX_VERTICES, "max_vertices")
        max_indices = _limit(max_indices, MAX_INDICES, "max_indices")
        try:
            tolerance = float(tolerance)
        except (TypeError, ValueError) as error:
            raise ValueError("tolerance must be finite and positive") from error
        if not np.isfinite(tolerance) or not 0 < tolerance <= np.finfo("f4").max:
            raise ValueError("tolerance must be a finite positive float32 value")
        tolerance = float(np.float32(tolerance))
        if tolerance == 0:
            raise ValueError("tolerance is too small for float32")
        if fill_rule not in ("nonzero", "evenodd"):
            raise ValueError("fill_rule must be 'nonzero' or 'evenodd'")
        try:
            border_width = float(border_width)
            border_miter_limit = float(border_miter_limit)
        except (TypeError, ValueError) as error:
            raise ValueError("border width and miter limit must be real scalars") from error
        if (not np.isfinite(border_width) or not 0 <= border_width <= np.finfo("f4").max):
            raise ValueError("border_width must be a finite nonnegative float32 value")
        if (not np.isfinite(border_miter_limit)
                or not 1 <= border_miter_limit <= np.finfo("f4").max):
            raise ValueError("border_miter_limit must be a finite float32 value >= 1")
        if border_join not in ("bevel", "miter", "round"):
            raise ValueError("border_join must be 'bevel', 'miter', or 'round'")
        if border_width > 0 and float(np.float32(border_width)) == 0:
            raise ValueError("border_width is too small for float32")
        border_width = float(np.float32(border_width))
        border_miter_limit = float(np.float32(border_miter_limit))
        if border_width > 0 and self._border_function is None:
            raise TessellationError("Lyon helper lacks border union support; rebuild or reinstall it")
        contours = list(contours)
        if attributes is not None:
            attributes = list(attributes)
            if len(attributes) != len(contours):
                raise ValueError("attributes must contain one array per contour")

        points, ends, attribute_arrays = [], [], []
        total = 0
        attribute_count = None
        uniform_attribute = None
        for index, contour in enumerate(contours):
            raw = np.asarray(contour)
            if raw.ndim != 2 or raw.shape[1] != 2:
                raise ValueError("each contour must have shape (2*n+1, 2)")
            if not np.issubdtype(raw.dtype, np.number) or np.iscomplexobj(raw):
                raise ValueError("coordinates must be real numeric values")
            if len(raw) and len(raw) % 2 != 1:
                raise ValueError("quadratic contours require an odd number of rows")
            total += len(raw)
            if total > MAX_SOURCE_POINTS:
                raise TessellationLimitError(f"source exceeds {MAX_SOURCE_POINTS} points")
            if not np.isfinite(raw).all() or np.any(np.abs(raw) > np.finfo("f4").max):
                raise ValueError("coordinates must be finite float32 values")
            point_array = np.ascontiguousarray(raw, dtype="f4")
            if attributes is not None:
                attr = np.asarray(attributes[index])
                if attr.ndim != 2 or len(attr) != len(raw):
                    raise ValueError("attribute arrays must match contour rows")
                if not np.issubdtype(attr.dtype, np.number) or np.iscomplexobj(attr):
                    raise ValueError("attributes must be real numeric values")
                if attribute_count is None:
                    attribute_count = attr.shape[1]
                if attr.shape[1] != attribute_count or attribute_count > MAX_ATTRIBUTES:
                    raise ValueError(f"attribute width must be consistent and <= {MAX_ATTRIBUTES}")
                if not np.isfinite(attr).all() or np.any(np.abs(attr) > np.finfo("f4").max):
                    raise ValueError("attributes must be finite float32 values")
                if len(raw):
                    attribute_arrays.append(np.ascontiguousarray(attr, dtype="f4"))
                    if border_width > 0:
                        if uniform_attribute is None:
                            uniform_attribute = attr[0]
                        if not np.all(attr[::2] == uniform_attribute):
                            raise ValueError("border union requires uniform endpoint attributes")
            if len(raw):
                points.append(point_array)
                ends.append(total)
        attribute_count = attribute_count or 0
        xy = np.concatenate(points) if points else np.empty((0, 2), dtype="f4")
        attrs = (np.concatenate(attribute_arrays) if attribute_arrays
                 else np.empty((len(xy), attribute_count), dtype="f4"))
        contour_ends = np.asarray(ends, dtype="u4")
        result = _MeshResult()
        try:
            args = [
                xy.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(xy),
                contour_ends.ctypes.data_as(ctypes.POINTER(ctypes.c_uint32)), len(ends),
                attrs.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), attribute_count,
                tolerance, int(fill_rule == "evenodd"),
            ]
            function = self._library.ml_lyon_tessellate
            if border_width > 0:
                function = self._border_function
                args.extend([border_width, ("bevel", "miter", "round").index(border_join),
                             border_miter_limit])
            code = function(*args, max_vertices, max_indices, ctypes.byref(result))
            if code == 1:
                raise ValueError("native Lyon adapter rejected invalid input")
            if code == 2:
                raise TessellationLimitError("Lyon fill exceeded its flattening or output limit")
            if code:
                raise TessellationError(f"Lyon fill failed (native status {code})")
            stride = 2 + attribute_count
            if result.vertex_floats % stride or result.index_count % 3:
                raise TessellationError("Lyon helper returned an invalid mesh layout")
            if (result.vertex_floats // stride > max_vertices
                    or result.index_count > max_indices):
                raise TessellationError("Lyon helper returned counts above requested limits")
            if ((result.vertex_floats and not result.vertices)
                    or (result.index_count and not result.indices)):
                raise TessellationError("Lyon helper returned missing mesh storage")
            if result.vertex_floats:
                rows = np.ctypeslib.as_array(result.vertices, (result.vertex_floats,)).reshape(-1, stride)
                positions = np.array(rows[:, :2], copy=True, order="C")
                out_attrs = np.array(rows[:, 2:], copy=True, order="C")
            else:
                positions = np.empty((0, 2), dtype="f4")
                out_attrs = np.empty((0, attribute_count), dtype="f4")
            indices = (np.ctypeslib.as_array(result.indices, (result.index_count,)).copy()
                       if result.index_count else np.empty(0, dtype="u4"))
            if indices.size and int(indices.max()) >= len(positions):
                raise TessellationError("Lyon helper returned an out-of-range index")
            return FillMesh(positions, indices, out_attrs, tolerance, fill_rule,
                            GENERATOR_ID + ("/border-union-1" if border_width > 0 else ""),
                            border_width, border_join if border_width > 0 else None,
                            border_miter_limit)
        finally:
            self._library.ml_lyon_free(ctypes.byref(result))
