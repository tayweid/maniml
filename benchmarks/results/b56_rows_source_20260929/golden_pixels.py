"""B5.6: the golden pin's phase_b frames, drawn natively as records and as
rows, frame by frame.

Runs the pin's golden classes as they stand: the pin states
MANIML_PATCH_SOURCE=records, as its phase_b digests were recorded, so they
pass untouched. Every phase_b message a pin's persistent cache produces is
also produced, right after it, by a shadow cache of its own with the patch
source taken out of the environment, as the viewer's Phase B selection
sends it (geometry.DEFAULT_PATCH_SOURCE, rows), fed the same scene at the
same moment. Both message sequences are drawn in order by two native
drivers of their own (one per pin and source, as a viewer's page keeps
one), and the images compared. Each records message's digest is held to
the pin's phase_b digest at its label, so the comparison is between the
frames the pin holds and the ones the selection sends.

Usage (from the worktree, MANIML_EPISODES naming a tree where both
episodes resolve): python golden_pixels.py OUT.json [unittest names...]
"""
import hashlib
import json
import os
import sys
import time
import unittest

import numpy as np

REPO = os.getcwd()
sys.path.insert(0, REPO)

import tests.test_retained_frame as pin_module
from maniml.web import geometry
from maniml.web.geometry import GeometryCache, parse_geometry_message
from maniml.web.wgpu_renderer import WgpuRenderer

out_path = sys.argv[1]
names = sys.argv[2:] or ["tests.test_retained_frame.FixtureGoldens", "tests.test_retained_frame.SyntheticGoldens",
                         "tests.test_retained_frame.SceneGoldens", "tests.test_retained_frame.EpisodeB2Goldens",
                         "tests.test_retained_frame.PriceDiscoveryGoldens"]
assert geometry.DEFAULT_PATCH_SOURCE == "rows", geometry.DEFAULT_PATCH_SOURCE

original_serialize = pin_module.serialize_scene
original_init = pin_module.Pin.__init__
original_check = pin_module.GoldenFile.check
pins = {}      # id(phase_b pin cache) -> state
results = []


class PinState:
    def __init__(self, pin):
        self.pin = pin
        self.shadow = GeometryCache()
        self.drivers = {"records": WgpuRenderer(), "rows": WgpuRenderer()}
        self.frames = []


def digest(message):
    return hashlib.blake2b(message, digest_size=16).hexdigest()


def draw(driver, message):
    header, payload = parse_geometry_message(message)
    header["renderer"] = "triangles"
    return np.asarray(driver.render(header, payload), dtype=np.int16)


def init(self, *args, **kwargs):
    original_init(self, *args, **kwargs)
    pins[id(self.caches["phase_b"])] = PinState(self)
    # The shadow must see a reset whenever the pin's caches do.
    original_reset = self.reset

    def reset():
        original_reset()
        pins[id(self.caches["phase_b"])].shadow.reset()
    self.reset = reset


def serialize(scene, cache=None, *, renderer=None):
    message = original_serialize(scene, cache, renderer=renderer)
    state = pins.get(id(cache)) if cache is not None else None
    if state is None or renderer != "phase_b" or state.pin.caches["phase_b"] is not cache:
        return message
    assert os.environ.get("MANIML_PATCH_SOURCE") == "records", "the pin states records"
    held = os.environ.pop("MANIML_PATCH_SOURCE")
    try:
        rows = original_serialize(scene, state.shadow, renderer="phase_b")
    finally:
        os.environ["MANIML_PATCH_SOURCE"] = held
    images = {"records": draw(state.drivers["records"], message), "rows": draw(state.drivers["rows"], rows)}
    diff = np.abs(images["records"] - images["rows"])
    header = parse_geometry_message(rows)[0]
    state.frames.append({"index": len(state.pin.frames), "records": digest(message), "rows": digest(rows),
                         "over_24": float((diff.max(axis=2) > 24).mean()), "max": int(diff.max()),
                         "pixels": int(diff.shape[0] * diff.shape[1]),
                         "rows_batches": sum("rows" in batch for batch in header["batches"]),
                         "batches": len(header["batches"])})
    return message


def check(self, test, case, pin, *, input):
    state = pins.pop(id(pin.caches["phase_b"]), None)
    if state is not None:
        for driver in state.drivers.values():
            driver.close()
        golden = self.cases.get(case, {}).get("frames", {})
        labels = list(pin.frames)
        for frame in state.frames:
            label = labels[frame["index"]]
            frame["label"] = label
            frame["pinned_phase_b"] = golden.get(label, {}).get("phase_b")
            frame["records_is_pinned"] = frame["records"] == frame["pinned_phase_b"]
            frame["rows_bytes_differ"] = frame["rows"] != frame["records"]
        results.append({"file": self.path.stem, "case": case, "frames": state.frames})
        worst = max((f["over_24"], f["max"]) for f in state.frames) if state.frames else None
        print(f"{self.path.stem:18s} {case:40s} frames {len(state.frames):3d} worst {worst} "
              f"records=pin {all(f['records_is_pinned'] for f in state.frames)}", flush=True)
    return original_check(self, test, case, pin, input=input)


pin_module.serialize_scene = serialize
pin_module.Pin.__init__ = init
pin_module.GoldenFile.check = check

started = time.time()
suite = unittest.defaultTestLoader.loadTestsFromNames(names)
outcome = unittest.TextTestRunner(verbosity=0, stream=open(os.devnull, "w")).run(suite)
frames = [frame for case in results for frame in case["frames"]]
summary = {
    "cases": len(results), "frames": len(frames),
    "max_over_24": max(f["over_24"] for f in frames), "max_channel": max(f["max"] for f in frames),
    "frames_differing": sum(f["max"] > 0 for f in frames),
    "records_is_pinned": sum(f["records_is_pinned"] for f in frames),
    "rows_bytes_differ": sum(f["rows_bytes_differ"] for f in frames),
    "frames_with_rows_batches": sum(f["rows_batches"] > 0 for f in frames),
    "tests_run": outcome.testsRun, "failures": len(outcome.failures), "errors": len(outcome.errors),
    "skipped": [(str(test), reason) for test, reason in outcome.skipped],
    "error_text": [text[-2000:] for _, text in outcome.errors + outcome.failures],
    "seconds": round(time.time() - started, 1),
}
json.dump({"summary": summary, "cases": results}, open(out_path, "w"), indent=1)
print(json.dumps(summary, indent=1))
