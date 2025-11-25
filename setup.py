"""
Setup script for maniml - Standalone Manim
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="maniml",
    version="0.0.1",
    author="maniml Contributors",
    description="Standalone Manim without external dependencies",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/tayweid/maniml",
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'maniml=manim.__main__:main',
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Education",
        "Topic :: Multimedia :: Graphics",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
    python_requires=">=3.7",
    install_requires=[
        'numpy',
        'moderngl',
        'moderngl-window',
        'pillow',
        'scipy',
        'colour',
        'pygments',
        'pyperclip',
        'IPython',
        'PyYAML',
        'addict',
        'PyOpenGL',
        'validators',
        'diskcache',
        'screeninfo',
        'appdirs',
        'matplotlib',
        'mapbox-earcut',
        'svgelements',
        'isosurfaces',
        'manimpango',
    ],
    extras_require={
        "dev": [
            "pytest",
            "black",
            "flake8",
        ],
    },
)