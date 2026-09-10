"""Reproduce exact source changes behind Write cache invalidation (no GPU)."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np
from benchmarks.renderer_motion import build_motion_sequence
from benchmarks.triangle_scene import TriangleMeshCache, prepare_triangle_frame, _MeshSource
from maniml.web.triangle_geometry import LyonFillTessellator


class AuditedCache(TriangleMeshCache):
    def reset_audit(self):
        self.causes = Counter()
        self.max_changed_point_distance = 0.

    def mesh(self, mobject, tessellator, uniforms, resolution, pixel_tolerance):
        source = _MeshSource.read(mobject)
        old = self._entries.get(id(mobject))
        fields = ('points', 'ends', 'rgba', 'normal')
        changed = tuple(name for name in fields if old is not None and
                        not np.array_equal(getattr(old.source, name), getattr(source, name)))
        self.causes[','.join(changed) if changed else ('unchanged' if old else 'absent')] += 1
        if old is not None and 'points' in changed and source.points.shape == old.source.points.shape:
            self.max_changed_point_distance = max(self.max_changed_point_distance,
                float(np.linalg.norm(source.points-old.source.points, axis=1).max()))
        return super().mesh(mobject, tessellator, uniforms, resolution, pixel_tolerance)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sequence, cache, tessellator = build_motion_sequence('tex_write'), AuditedCache(), LyonFillTessellator()
    cache.reset_audit()
    sequence.apply(0)
    for _ in range(2):
        prepare_triangle_frame(sequence.snapshot(0).scene, tessellator, diagnostic=True, mesh_cache=cache)
    cache.reset_audit()
    frames = []
    for index in range(sequence.steps):
        sequence.apply(index)
        frame = prepare_triangle_frame(sequence.snapshot(index).scene, tessellator, diagnostic=True, mesh_cache=cache)
        frames.append({'index': index, 'mesh_cache': frame.mesh_cache_stats})
    sequence.finish()
    paths = [Path(__file__), ROOT/'benchmarks/renderer_motion.py', ROOT/'benchmarks/triangle_scene.py',
             ROOT/'maniml/animation/creation.py', ROOT/'maniml/mobject/types/vectorized_mobject.py']
    report = {'scope': 'CPU source audit, two warm frames excluded; no performance measurement.',
              'source_files_sha256': {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in paths},
              'cache_lookup_causes': dict(cache.causes),
              'max_changed_point_distance_world_units': cache.max_changed_point_distance,
              'frames': frames,
              'interpretation': 'Points are compared exactly, after shader-data preparation as in the timed harness. Mathematical shape invariance does not imply identical interpolated float32 source bytes. Normal changes also participate in the existing geometry key.'}
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('frames','source_files_sha256')}, indent=2))


if __name__ == '__main__':
    main()
