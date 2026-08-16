from __future__ import annotations

import os
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import yaml

from maniml.utils.cache import cache_on_disk
from maniml.config import manim_config
from maniml.config import get_manim_dir
from maniml.logger import log


TEX_COMPILATION_TIMEOUT = 120
DVISVGM_TIMEOUT = 60


def _run_tex_tool(
    command: list[str | os.PathLike[str]],
    *,
    tool: str,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    """Run one bounded TeX tool and turn launch failures into user errors."""
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise LatexError(
            f"{tool} executable was not found; install it and ensure it is on PATH"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise LatexError(f"{tool} timed out after {timeout:g} seconds") from exc
    except OSError as exc:
        raise LatexError(f"Could not run {tool}: {exc}") from exc


def _error_output(process: subprocess.CompletedProcess[str]) -> str:
    """Return a bounded diagnostic without flooding a terminal or web response."""
    output = (process.stderr or process.stdout or "").strip()
    return output[-4000:]


def get_tex_template_config(template_name: str) -> dict[str, str]:
    name = template_name.replace(" ", "_").lower()
    template_path = os.path.join(get_manim_dir(), "tex_templates.yml")
    with open(template_path, encoding="utf-8") as tex_templates_file:
        templates_dict = yaml.safe_load(tex_templates_file)
    if name not in templates_dict:
        log.warning(f"Cannot recognize template {name}, falling back to 'default'.")
        name = "default"
    return templates_dict[name]


@lru_cache
def get_tex_config(template: str = "") -> tuple[str, str]:
    """
    Returns a compiler and preamble to use for rendering LaTeX
    """
    template = template or manim_config.tex.template
    config = get_tex_template_config(template)
    return config["compiler"], config["preamble"]


def get_full_tex(content: str, preamble: str = ""):
    return "\n\n".join((
        "\\documentclass[preview]{standalone}",
        preamble,
        "\\begin{document}",
        content,
        "\\end{document}"
    )) + "\n"


@lru_cache(maxsize=128)
def latex_to_svg(
    latex: str,
    template: str = "",
    additional_preamble: str = "",
    short_tex: str = "",
    show_message_during_execution: bool = True,
) -> str:
    """Convert LaTeX string to SVG string.

    Args:
        latex: LaTeX source code
        template: Path to a template LaTeX file
        additional_preamble: String including any added "\\usepackage{...}" style imports

    Returns:
        str: SVG source code

    Raises:
        LatexError: If LaTeX compilation fails
        NotImplementedError: If compiler is not supported
    """
    if show_message_during_execution:
        message = f"Writing {(short_tex or latex)[:70]}..."
    else:
        message = ""

    compiler, preamble = get_tex_config(template)

    preamble = "\n".join([preamble, additional_preamble])
    full_tex = get_full_tex(latex, preamble)
    return full_tex_to_svg(full_tex, compiler, message)


@cache_on_disk
def full_tex_to_svg(full_tex: str, compiler: str = "latex", message: str = ""):
    if message:
        print(message, end="\r")

    if compiler == "latex":
        dvi_ext = ".dvi"
    elif compiler == "xelatex":
        dvi_ext = ".xdv"
    else:
        raise NotImplementedError(f"Compiler '{compiler}' is not implemented")

    # Write intermediate files to a temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        tex_path = Path(temp_dir, "working").with_suffix(".tex")
        dvi_path = tex_path.with_suffix(dvi_ext)

        # Write tex file
        tex_path.write_text(full_tex, encoding="utf-8")

        # Run latex compiler
        process = _run_tex_tool(
            [
                compiler,
                *(['-no-pdf'] if compiler == "xelatex" else []),
                "-interaction=batchmode",
                "-halt-on-error",
                f"-output-directory={temp_dir}",
                tex_path
            ],
            tool=compiler,
            timeout=TEX_COMPILATION_TIMEOUT,
        )

        if process.returncode != 0:
            # Handle error
            error_str = ""
            log_path = tex_path.with_suffix(".log")
            if log_path.exists():
                content = log_path.read_text(encoding="utf-8", errors="replace")
                error_match = re.search(r"(?<=\n! ).*\n.*\n", content)
                if error_match:
                    error_str = error_match.group()
            diagnostic = error_str.strip() or _error_output(process)
            message_text = f"{compiler} compilation failed"
            if diagnostic:
                message_text += f":\n{diagnostic}"
            raise LatexError(message_text)

        # Run dvisvgm and capture output directly
        process = _run_tex_tool(
            [
                "dvisvgm",
                dvi_path,
                "-n",  # no fonts
                "-v", "0",  # quiet
                "--stdout",  # output to stdout instead of file
            ],
            tool="dvisvgm",
            timeout=DVISVGM_TIMEOUT,
        )

        if process.returncode != 0:
            diagnostic = _error_output(process)
            message_text = "dvisvgm conversion failed"
            if diagnostic:
                message_text += f":\n{diagnostic}"
            raise LatexError(message_text)

        result = process.stdout
        if not result.strip():
            raise LatexError("dvisvgm produced no SVG output")

    if message:
        print(" " * len(message), end="\r")

    return result


class LatexError(Exception):
    pass
