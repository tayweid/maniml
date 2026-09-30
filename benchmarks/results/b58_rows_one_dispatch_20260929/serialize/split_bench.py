import timeit, numpy as np
from maniml.web.gpu_program_geometry import split_rows, GEOMETRY_COLUMNS, PAINT_COLUMNS
rng = np.random.default_rng(0)
for n in (9, 25, 101):
    rows = rng.random((n, 17), dtype=np.float32)
    rows[:, 3:7] = (1, 1, 1, 1); rows[:, 9:13] = (.2, .3, .4, 1)
    prev = split_rows(rows)
    moved = rows.copy(); moved[:, :3] += 1
    t = timeit.timeit(lambda: split_rows(moved, prev), number=20000) / 20000 * 1e6
    t0 = timeit.timeit(lambda: split_rows(rows, prev), number=20000) / 20000 * 1e6
    gi = np.array(GEOMETRY_COLUMNS)
    t1 = timeit.timeit(lambda: moved[:, gi].tobytes(), number=20000) / 20000 * 1e6
    t2 = timeit.timeit(lambda: moved.tobytes(), number=20000) / 20000 * 1e6
    print(f"n={n}: moved {t:.2f} us, still {t0:.2f} us, geometry fancy+tobytes {t1:.2f} us, whole tobytes {t2:.2f} us")
