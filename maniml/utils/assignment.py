"""The linear sum assignment problem, without scipy.

`scipy.optimize.linear_sum_assignment` matched a Tex string's labelled
glyphs to its unlabelled ones (a few dozen at a time). This is the
Hungarian algorithm in its O(n²m) potentials form, for a rectangular cost
matrix, returning the row and column indices of the minimum-cost matching
as scipy does. tests/test_assignment.py holds it to scipy where scipy is
installed, and to brute force always.
"""

from __future__ import annotations

import math

import numpy as np


def linear_sum_assignment(cost_matrix, maximize: bool = False) -> tuple[np.ndarray, np.ndarray]:
    cost = np.asarray(cost_matrix, dtype=float)
    if cost.ndim != 2:
        raise ValueError("expected a 2-D cost matrix")
    if maximize:
        cost = -cost
    if not np.all(np.isfinite(cost)):
        raise ValueError("the cost matrix must be finite")
    transposed = cost.shape[0] > cost.shape[1]
    if transposed:
        cost = cost.T
    n, m = cost.shape
    if n == 0:
        rows, cols = np.zeros(0, dtype=int), np.zeros(0, dtype=int)
        return (cols, rows) if transposed else (rows, cols)

    # Potentials u (rows) and v (columns), and p[j]: the row matched to
    # column j (1-based; 0 is the virtual row). E-maxx's formulation.
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [math.inf] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = math.inf
            j1 = 0
            row = cost[i0 - 1]
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = row[j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    pairs = sorted((p[j] - 1, j - 1) for j in range(1, m + 1) if p[j])
    rows = np.array([r for r, _ in pairs], dtype=int)
    cols = np.array([c for _, c in pairs], dtype=int)
    if transposed:
        order = np.argsort(cols, kind="stable")
        return cols[order], rows[order]
    return rows, cols
