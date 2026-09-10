"""Opt-in CPU fill-mesh experiment; not used by the production serializer.

The input remains a list of Manim quadratic control-point contours. The output
is disposable drawing data. Coordinates are two-dimensional *tessellation*
coordinates: the caller chooses a projection/local plane and converts a pixel
error tolerance to that space. This module does not assume world xy is valid
for arbitrary 3D paths, or claim perspective/error or paint-field equivalence.

Build the pinned native helper as documented in tools/lyon_fill/README.md and
pass its filename explicitly, or set MANIML_LYON_LIBRARY. Importing this module
does not build, download, or load native code.
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


class LyonFillTessellator:
    """A reusable loader for the pinned, Python-version-independent C ABI.

    Each call has independent native tessellator state. Returned arrays own
    their storage; native allocation is released before the call returns.
    Nothing is cached using mutable source-array identity.
    """

    def __init__(self, library_path: str | os.PathLike | None = None):
        selected = library_path or os.environ.get("MANIML_LYON_LIBRARY")
        if not selected:
            raise TessellationError(
                "Lyon is optional for the A0 prototype. Build tools/lyon_fill and "
                "pass library_path or set MANIML_LYON_LIBRARY."
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
        self._library.ml_lyon_free.argtypes = [ctypes.POINTER(_MeshResult)]
        self._library.ml_lyon_free.restype = None

    def tessellate(
        self,
        contours: Sequence[np.ndarray],
        *,
        attributes: Sequence[np.ndarray] | None = None,
        tolerance: float = 0.25,
        fill_rule: str = "nonzero",
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
        contours = list(contours)
        if attributes is not None:
            attributes = list(attributes)
            if len(attributes) != len(contours):
                raise ValueError("attributes must contain one array per contour")

        points, ends, attribute_arrays = [], [], []
        total = 0
        attribute_count = None
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
            code = self._library.ml_lyon_tessellate(
                xy.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(xy),
                contour_ends.ctypes.data_as(ctypes.POINTER(ctypes.c_uint32)), len(ends),
                attrs.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), attribute_count,
                tolerance, int(fill_rule == "evenodd"), max_vertices, max_indices,
                ctypes.byref(result),
            )
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
            return FillMesh(positions, indices, out_attrs, tolerance, fill_rule)
        finally:
            self._library.ml_lyon_free(ctypes.byref(result))
