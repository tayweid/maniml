"""A banded linear solve, without scipy.

`scipy.linalg.solve_banded` solved the smoothing spline's system in
bezier.py (two lower and one upper diagonal). This is LU with partial
pivoting kept within the band, as Numerical Recipes' bandec/banbks do:
O(n·(l+u)²) rather than the dense O(n³), so a path of thousands of anchors
smooths as it did. The input is scipy's diagonal-ordered form
(``ab[u + i - j, j] == A[i, j]``); tests/test_banded.py holds it to a
dense solve, and to scipy where scipy is installed.
"""

from __future__ import annotations

import numpy as np


def solve_banded(l_and_u: tuple[int, int], ab, b) -> np.ndarray:
    l, u = l_and_u
    ab = np.asarray(ab, dtype=float)
    b = np.asarray(b, dtype=float)
    n = ab.shape[1]
    if ab.shape[0] != l + u + 1:
        raise ValueError(f"expected {l + u + 1} diagonals, got {ab.shape[0]}")
    single = b.ndim == 1
    rhs = b.reshape(n, -1).copy()
    width = l + u + 1
    # Compact rows: a[i, k] holds A[i, i - l + k], the row's band from its
    # lowest diagonal up.
    a = np.zeros((n, width))
    for k in range(width):
        offset = k - l  # column = row + offset
        rows = np.arange(max(0, -offset), min(n, n - offset))
        a[rows, k] = ab[u - offset, rows + offset]
    # Shift the first l rows left so every row starts at its first column.
    for i in range(l):
        shift = l - i
        a[i, :width - shift] = a[i, shift:]
        a[i, width - shift:] = 0
    # Elimination with partial pivoting; a pivot row swap stays in the band.
    for k in range(n):
        span = min(k + l + 1, n)
        pivot = k + int(np.argmax(np.abs(a[k:span, 0])))
        if a[pivot, 0] == 0:
            raise np.linalg.LinAlgError("singular banded matrix")
        if pivot != k:
            a[[k, pivot]] = a[[pivot, k]]
            rhs[[k, pivot]] = rhs[[pivot, k]]
        for i in range(k + 1, span):
            factor = a[i, 0] / a[k, 0]
            a[i, :-1] = a[i, 1:] - factor * a[k, 1:]
            a[i, -1] = 0
            rhs[i] -= factor * rhs[k]
    # Back substitution over the eliminated band.
    x = np.zeros_like(rhs)
    for i in range(n - 1, -1, -1):
        acc = rhs[i].copy()
        for k in range(1, min(width, n - i)):
            acc -= a[i, k] * x[i + k]
        x[i] = acc / a[i, 0]
    return x[:, 0] if single else x
