"""Rotations as unit quaternions, in scipy's conventions, without scipy.

`scipy.spatial.transform.Rotation` was 73 MB of scipy for five methods
(2026-09-30, the dependency trim). This is the part maniml used: scalar-last
quaternions ``[x, y, z, w]``, rotation vectors, matrices, Euler angles in
scipy's sequence notation (lowercase extrinsic, uppercase intrinsic), and
composition with ``*``. Held to scipy's numbers by tests/test_rotation.py
wherever scipy is installed.
"""

from __future__ import annotations

import math
import warnings

import numpy as np

_AXES = {"x": 0, "y": 1, "z": 2}


# The arithmetic below is scipy's (_rotation_cy.pyx, 1.18), operation for
# operation, so the frames the golden pins hold (tests/test_retained_frame)
# come out byte for byte as they did with scipy.


def _unit(q: np.ndarray) -> np.ndarray:
    x, y, z, w = q
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm == 0:
        raise ValueError("a zero quaternion is not a rotation")
    return np.array([x / norm, y / norm, z / norm, w / norm])


def _compose(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """The Hamilton product p ⊗ q, scalar last: rotate by q, then by p."""
    cross = (
        p[1] * q[2] - p[2] * q[1],
        p[2] * q[0] - p[0] * q[2],
        p[0] * q[1] - p[1] * q[0],
    )
    return np.array([
        p[3] * q[0] + q[3] * p[0] + cross[0],
        p[3] * q[1] + q[3] * p[1] + cross[1],
        p[3] * q[2] + q[3] * p[2] + cross[2],
        p[3] * q[3] - p[0] * q[0] - p[1] * q[1] - p[2] * q[2],
    ])


def _elementary(axis: int, angle: float) -> np.ndarray:
    q = np.zeros(4)
    q[axis] = math.sin(angle / 2)
    q[3] = math.cos(angle / 2)
    return q


class Rotation:
    __slots__ = ("_quat",)

    def __init__(self, quat: np.ndarray):
        self._quat = np.asarray(quat, dtype=float)

    # Constructors

    @classmethod
    def identity(cls) -> "Rotation":
        return cls(np.array([0.0, 0.0, 0.0, 1.0]))

    @classmethod
    def from_quat(cls, quat) -> "Rotation":
        return cls(_unit(np.asarray(quat, dtype=float)))

    @classmethod
    def from_rotvec(cls, rotvec) -> "Rotation":
        v = np.asarray(rotvec, dtype=float)
        angle = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
        if angle <= 1e-3:
            # sin(a/2)/a as a series, so a tiny angle keeps its direction.
            angle2 = angle * angle
            scale = 0.5 - angle2 / 48 + angle2 * angle2 / 3840
        else:
            scale = math.sin(angle / 2) / angle
        return cls(np.array([scale * v[0], scale * v[1], scale * v[2], math.cos(angle / 2)]))

    @classmethod
    def from_matrix(cls, matrix) -> "Rotation":
        m = np.asarray(matrix, dtype=float)
        trace = m[0, 0] + m[1, 1] + m[2, 2]
        if trace > 0:
            s = math.sqrt(trace + 1.0) * 2
            q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s]
        elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
            s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
            q = [0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
        elif m[1, 1] > m[2, 2]:
            s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
            q = [(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
        else:
            s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
            q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]
        return cls(_unit(np.array(q)))

    @classmethod
    def from_euler(cls, seq: str, angles, degrees: bool = False) -> "Rotation":
        """scipy's sequences: 'xyz' (lowercase) rotates about the fixed
        frame's axes in turn, 'XYZ' (uppercase) about the body's."""
        extrinsic, axes = _parse_sequence(seq)
        angles = np.atleast_1d(np.asarray(angles, dtype=float))
        if degrees:
            angles = np.radians(angles)
        if len(angles) != len(axes):
            raise ValueError(f"expected {len(axes)} angles for sequence {seq!r}")
        result = np.array([0.0, 0.0, 0.0, 1.0])
        for axis, angle in zip(axes, angles):
            step = _elementary(axis, float(angle))
            # Extrinsic: each rotation is applied after the ones before it
            # in the fixed frame; intrinsic: in the rotated frame.
            result = _compose(step, result) if extrinsic else _compose(result, step)
        return cls(result)

    # Representations

    def as_quat(self) -> np.ndarray:
        return self._quat.copy()

    def as_rotvec(self) -> np.ndarray:
        q = self._quat
        x, y, z, w = q
        if w < 0 or (w == 0 and (x < 0 or (x == 0 and (y < 0 or (y == 0 and z < 0))))):
            x, y, z, w = -x, -y, -z, -w
        angle = 2 * math.atan2(math.sqrt(x * x + y * y + z * z), w)
        if angle <= 1e-3:
            angle2 = angle * angle
            scale = 2 + angle2 / 12 + 7 * angle2 * angle2 / 2880
        else:
            scale = angle / math.sin(angle / 2)
        return np.array([scale * x, scale * y, scale * z])

    def as_matrix(self) -> np.ndarray:
        x, y, z, w = self._quat
        x2, y2, z2, w2 = x * x, y * y, z * z, w * w
        xy, zw, xz, yw, yz, xw = x * y, z * w, x * z, y * w, y * z, x * w
        return np.array([
            [x2 - y2 - z2 + w2, 2 * (xy - zw), 2 * (xz + yw)],
            [2 * (xy + zw), -x2 + y2 - z2 + w2, 2 * (yz - xw)],
            [2 * (xz - yw), 2 * (yz + xw), -x2 - y2 + z2 + w2],
        ])

    def as_euler(self, seq: str, degrees: bool = False) -> np.ndarray:
        """Bernardes & Viollet's algorithm, as scipy implements it."""
        extrinsic, axes = _parse_sequence(seq)
        if len(axes) != 3:
            raise ValueError("Euler angles need a sequence of three axes")
        i, j, k = axes if extrinsic else axes[::-1]
        symmetric = i == k
        if symmetric:
            k = 3 - i - j
        sign = (i - j) * (j - k) * (k - i) // 2
        q = self._quat
        if symmetric:
            a, b, c, d = q[3], q[i], q[j], q[k] * sign
        else:
            a = q[3] - q[j]
            b = q[i] + q[k] * sign
            c = q[j] + q[3]
            d = q[k] * sign - q[i]
        angles = np.zeros(3)
        angles[1] = 2 * math.atan2(math.hypot(c, d), math.hypot(a, b))
        eps = 1e-7
        if abs(angles[1]) <= eps:
            case = 1
        elif abs(angles[1] - math.pi) <= eps:
            case = 2
        else:
            case = 0
        half_sum = math.atan2(b, a)
        half_diff = math.atan2(d, c)
        if case == 0:
            angles[0] = half_sum - half_diff
            angles[2] = half_sum + half_diff
        else:
            angles[2] = 0
            if case == 1:
                angles[0] = 2 * half_sum
            else:
                angles[0] = 2 * half_diff * (-1 if extrinsic else 1)
        if not symmetric:
            angles[2] *= sign
            angles[1] -= math.pi / 2
        if not extrinsic:
            angles[0], angles[2] = angles[2], angles[0]
        for n in range(3):
            if angles[n] < -math.pi:
                angles[n] += 2 * math.pi
            elif angles[n] > math.pi:
                angles[n] -= 2 * math.pi
        if case != 0:
            warnings.warn(
                "Gimbal lock detected. Setting third angle to zero since it "
                "is not possible to uniquely determine all angles.",
                UserWarning, stacklevel=2,
            )
        return np.degrees(angles) if degrees else angles

    # Algebra

    def __mul__(self, other: "Rotation") -> "Rotation":
        """``p * q`` rotates by q first, then by p, as scipy's does."""
        return Rotation(_unit(_compose(self._quat, other._quat)))

    def inv(self) -> "Rotation":
        q = self._quat.copy()
        q[:3] *= -1
        return Rotation(q)

    def apply(self, vectors, inverse: bool = False) -> np.ndarray:
        matrix = self.as_matrix()
        if inverse:
            matrix = matrix.T
        return np.asarray(vectors, dtype=float) @ matrix.T

    def __repr__(self) -> str:
        return f"Rotation(quat={self._quat.tolist()})"


def _parse_sequence(seq: str) -> tuple[bool, list[int]]:
    if not 1 <= len(seq) <= 3:
        raise ValueError(f"expected a sequence of 1 to 3 axes, got {seq!r}")
    if seq.islower():
        extrinsic = True
    elif seq.isupper():
        extrinsic = False
    else:
        raise ValueError(f"a sequence is all lowercase or all uppercase, got {seq!r}")
    axes = [_AXES[char] for char in seq.lower()]
    for first, second in zip(axes, axes[1:]):
        if first == second:
            raise ValueError(f"consecutive axes must differ, got {seq!r}")
    return extrinsic, axes
