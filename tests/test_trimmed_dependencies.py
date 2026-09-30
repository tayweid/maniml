"""The numpy replacements for what scipy did (the dependency trim,
2026-09-30): rotations, the banded solve behind smooth handles, and the
assignment behind Tex glyph labelling. Each is held to scipy's numbers
where scipy is installed (the dev group has it) and to an independent
check always."""

import itertools
import unittest
import warnings

import numpy as np

from maniml.utils.assignment import linear_sum_assignment
from maniml.utils.banded import solve_banded
from maniml.utils.rotation import Rotation

try:
    import scipy.linalg
    import scipy.optimize
    from scipy.spatial.transform import Rotation as ScipyRotation
except ImportError:  # pragma: no cover - the app's environment
    ScipyRotation = None

SEQUENCES = ["zxz", "zxy", "xyz", "zyx", "yxy", "ZXZ", "ZXY", "XYZ", "ZYX", "YXY"]


def random_quats(count, seed=0):
    rng = np.random.default_rng(seed)
    quats = rng.normal(size=(count, 4))
    return quats / np.linalg.norm(quats, axis=1, keepdims=True)


class RotationTests(unittest.TestCase):
    def test_round_trips_and_matrix_orthogonality(self):
        for quat in random_quats(50):
            rot = Rotation.from_quat(quat)
            matrix = rot.as_matrix()
            np.testing.assert_allclose(matrix @ matrix.T, np.eye(3), atol=1e-12)
            self.assertAlmostEqual(np.linalg.det(matrix), 1.0)
            back = Rotation.from_rotvec(rot.as_rotvec())
            np.testing.assert_allclose(back.as_matrix(), matrix, atol=1e-12)
            np.testing.assert_allclose(Rotation.from_matrix(matrix).as_matrix(), matrix, atol=1e-12)
            for seq in SEQUENCES:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    angles = rot.as_euler(seq)
                np.testing.assert_allclose(
                    Rotation.from_euler(seq, angles).as_matrix(), matrix, atol=1e-10, err_msg=seq)

    def test_composition_applies_the_right_operand_first(self):
        a = Rotation.from_rotvec([0.3, 0, 0])
        b = Rotation.from_rotvec([0, 0.7, 0])
        np.testing.assert_allclose((a * b).as_matrix(), a.as_matrix() @ b.as_matrix(), atol=1e-12)
        v = np.array([1.0, 2.0, 3.0])
        np.testing.assert_allclose((a * b).apply(v), a.apply(b.apply(v)), atol=1e-12)
        np.testing.assert_allclose((a * a.inv()).as_quat(), [0, 0, 0, 1], atol=1e-12)

    def test_small_angles_keep_their_direction(self):
        tiny = Rotation.from_rotvec([1e-9, 0, 0])
        np.testing.assert_allclose(tiny.as_rotvec(), [1e-9, 0, 0], rtol=1e-6)
        np.testing.assert_allclose(Rotation.identity().as_rotvec(), [0, 0, 0])

    @unittest.skipIf(ScipyRotation is None, "scipy is not installed")
    def test_matches_scipy(self):
        for quat in random_quats(40, seed=1):
            ours, theirs = Rotation.from_quat(quat), ScipyRotation.from_quat(quat)
            np.testing.assert_allclose(ours.as_matrix(), theirs.as_matrix(), atol=1e-12)
            np.testing.assert_allclose(ours.as_rotvec(), theirs.as_rotvec(), atol=1e-12)
            for seq in SEQUENCES:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    np.testing.assert_allclose(ours.as_euler(seq), theirs.as_euler(seq), atol=1e-9, err_msg=seq)
        rng = np.random.default_rng(2)
        for seq in SEQUENCES:
            angles = rng.uniform(-np.pi, np.pi, size=3)
            np.testing.assert_allclose(
                Rotation.from_euler(seq, angles).as_quat() * np.sign(Rotation.from_euler(seq, angles).as_quat()[3] or 1),
                ScipyRotation.from_euler(seq, angles).as_quat() * np.sign(ScipyRotation.from_euler(seq, angles).as_quat()[3] or 1),
                atol=1e-12, err_msg=seq)
        for v in rng.normal(size=(20, 3)):
            np.testing.assert_allclose(Rotation.from_rotvec(v).as_quat(), ScipyRotation.from_rotvec(v).as_quat(), atol=1e-12)
        p, q = (Rotation.from_quat(x) for x in random_quats(2, seed=3))
        sp, sq = (ScipyRotation.from_quat(x) for x in random_quats(2, seed=3))
        np.testing.assert_allclose((p * q).as_matrix(), (sp * sq).as_matrix(), atol=1e-12)
        # Gimbal lock: the same angles, and the same warning scipy gives.
        locked = Rotation.from_euler("zxz", [0.4, 0.0, 0.9])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            ours = locked.as_euler("zxz")
        self.assertTrue(any("Gimbal" in str(w.message) for w in caught))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            theirs = ScipyRotation.from_euler("zxz", [0.4, 0.0, 0.9]).as_euler("zxz")
        np.testing.assert_allclose(ours, theirs, atol=1e-9)


class BandedTests(unittest.TestCase):
    def banded(self, n, l, u, seed):
        rng = np.random.default_rng(seed)
        ab = rng.normal(size=(l + u + 1, n))
        ab[u] += 4  # diagonally dominant, so the system is well posed
        dense = np.zeros((n, n))
        for i in range(n):
            for j in range(max(0, i - l), min(n, i + u + 1)):
                dense[i, j] = ab[u + i - j, j]
        return ab, dense

    def test_matches_a_dense_solve(self):
        for n, l, u, seed in [(1, 0, 0, 0), (2, 1, 1, 1), (7, 2, 1, 2), (40, 2, 1, 3), (25, 1, 3, 4), (9, 3, 3, 5)]:
            ab, dense = self.banded(n, l, u, seed)
            rng = np.random.default_rng(seed + 100)
            b = rng.normal(size=n)
            np.testing.assert_allclose(solve_banded((l, u), ab, b), np.linalg.solve(dense, b), atol=1e-9)
            b2 = rng.normal(size=(n, 3))
            np.testing.assert_allclose(solve_banded((l, u), ab, b2), np.linalg.solve(dense, b2), atol=1e-9)

    def test_pivoting_handles_a_zero_diagonal(self):
        ab = np.array([[0.0, 1.0, 1.0], [0.0, 0.0, 2.0], [3.0, 3.0, 0.0]])  # u=1, l=1
        dense = np.array([[0.0, 1.0, 0.0], [3.0, 0.0, 1.0], [0.0, 3.0, 2.0]])
        b = np.array([1.0, 2.0, 3.0])
        np.testing.assert_allclose(solve_banded((1, 1), ab, b), np.linalg.solve(dense, b), atol=1e-12)

    @unittest.skipIf(ScipyRotation is None, "scipy is not installed")
    def test_matches_scipy(self):
        for n, l, u, seed in [(30, 2, 1, 6), (12, 1, 1, 7), (50, 3, 2, 8)]:
            ab, _ = self.banded(n, l, u, seed)
            b = np.random.default_rng(seed).normal(size=(n, 2))
            np.testing.assert_allclose(solve_banded((l, u), ab, b), scipy.linalg.solve_banded((l, u), ab, b), atol=1e-9)

    def test_smooth_handles_still_come_out_the_same(self):
        from maniml.utils.bezier import get_smooth_cubic_bezier_handle_points
        points = np.array([[0, 0, 0], [1, 2, 0], [3, 1, 0], [4, 4, 0], [6, 0, 0]], dtype=float)
        h1, h2 = get_smooth_cubic_bezier_handle_points(points)
        self.assertEqual(h1.shape, (4, 3))
        # C2 continuity at the interior anchors: the second differences agree.
        for i in range(1, 4):
            np.testing.assert_allclose(h1[i] - points[i], points[i] - h2[i - 1], atol=1e-9)


class AssignmentTests(unittest.TestCase):
    def brute(self, cost):
        n, m = cost.shape
        best, best_cols = np.inf, None
        if n <= m:
            for cols in itertools.permutations(range(m), n):
                total = sum(cost[i, c] for i, c in enumerate(cols))
                if total < best - 1e-12:
                    best, best_cols = total, cols
        else:
            return self.brute(cost.T)
        return best

    def test_matches_brute_force(self):
        rng = np.random.default_rng(0)
        for shape in [(1, 1), (3, 3), (4, 6), (6, 4), (5, 5), (2, 7)]:
            for _ in range(5):
                cost = rng.integers(0, 10, size=shape).astype(float)
                rows, cols = linear_sum_assignment(cost)
                self.assertEqual(len(rows), min(shape))
                self.assertEqual(len(set(rows)), len(rows))
                self.assertEqual(len(set(cols)), len(cols))
                self.assertAlmostEqual(cost[rows, cols].sum(), self.brute(cost))

    def test_empty_and_maximize(self):
        rows, cols = linear_sum_assignment(np.zeros((0, 3)))
        self.assertEqual((len(rows), len(cols)), (0, 0))
        cost = np.array([[1.0, 5.0], [4.0, 2.0]])
        rows, cols = linear_sum_assignment(cost, maximize=True)
        self.assertEqual(cost[rows, cols].sum(), 9.0)

    @unittest.skipIf(ScipyRotation is None, "scipy is not installed")
    def test_matches_scipy(self):
        rng = np.random.default_rng(1)
        for shape in [(8, 8), (5, 12), (12, 5), (30, 30)]:
            cost = rng.normal(size=shape)
            rows, cols = linear_sum_assignment(cost)
            srows, scols = scipy.optimize.linear_sum_assignment(cost)
            np.testing.assert_array_equal(rows, srows)
            self.assertAlmostEqual(cost[rows, cols].sum(), cost[srows, scols].sum())


if __name__ == "__main__":
    unittest.main()
