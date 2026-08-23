"""Run the rail simulation: rail.js + presentation.js driven in Node
against a DOM stub (tests/rail_sim.cjs). The scripted scenes are the
executable form of the rail's behavioral claims — hold at the pausepoint,
one steady link per stretch, lift the ring, pulse only true stacks, land
on arrival, playback position tracked by index."""

import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


@unittest.skipIf(shutil.which("node") is None, "node not available")
class RailSimulationTests(unittest.TestCase):
    def test_rail_discipline(self):
        result = subprocess.run(
            ["node", str(REPO / "tests" / "rail_sim.cjs")],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(
            result.returncode, 0,
            f"rail simulation failed:\n{result.stdout}\n{result.stderr}")


if __name__ == "__main__":
    unittest.main()
