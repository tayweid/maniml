#!/usr/bin/env python
import subprocess
import sys

# Run the test and capture output
proc = subprocess.Popen(
    [sys.executable, '-m', 'manim', 'test_simple_three.py', 'TestSimpleThree'],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True
)

# Read output line by line
while True:
    line = proc.stdout.readline()
    if not line:
        break
    print(line.rstrip())
    
    # Simulate key presses after certain output
    if "Tips: Using the keys" in line:
        print("\n--- Simulating: Press LEFT arrow twice ---")
    if "Reverse to animation 1/3" in line:
        print("\n--- Now at animation 1/3, simulating: Press RIGHT arrow ---")
        break

proc.kill()