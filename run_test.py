#!/usr/bin/env python3
"""Run test with window display."""

import sys
import os

# Add current directory to path so we can import manim
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Now run the ManimGL main with our test file
from manim.renderer.opengl.__main__ import main

# Set up arguments
original_argv = sys.argv.copy()
sys.argv = ['manimgl', 'test_table.py', 'TestTable']

try:
    main()
finally:
    sys.argv = original_argv