from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
import tempfile
from functools import lru_cache

import manimpango
import pygments
import pygments.formatters
import pygments.lexers

from manim.config import manim_config
from manim.constants import DEFAULT_PIXEL_WIDTH, FRAME_WIDTH
from manim.constants import NORMAL
from manim.logger import log
from manim.mobject.svg.string_mobject import StringMobject
from manim.utils.cache import cache_on_disk
from manim.utils.color import color_to_hex
from manim.utils.color import int_to_hex
from manim.utils.simple_functions import hash_string

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable

    from manim.mobject.types.vectorized_mobject import VGroup
    from manim.typing import ManimColor, Span, Selector


TEXT_MOB_SCALE_FACTOR = 0.0076
DEFAULT_LINE_SPACING_SCALE = 0.6
# Ensure the canvas is large enough to hold all glyphs.
DEFAULT_CANVAS_WIDTH = 16384
DEFAULT_CANVAS_HEIGHT = 16384


# Temporary handler
class _Alignment:
    VAL_DICT = {
        "LEFT": 0,
        "CENTER": 1,
        "RIGHT": 2
    }

    def __init__(self, s: str):
        self.value = _Alignment.VAL_DICT[s.upper()]


@lru_cache(maxsize=128)
@cache_on_disk
def markup_to_svg(
    markup_str: str,
    justify: bool = False,
    indent: float = 0,
    alignment: str = "CENTER",
    line_width: float | None = None,
) -> str:
    validate_error = manimpango.MarkupUtils.validate(markup_str)
    if validate_error:
        raise ValueError(
            f"Invalid markup string \"{markup_str}\"\n" + \
            f"{validate_error}"
        )

    # `manimpango` is under construction,
    # so the following code is intended to suit its interface
    alignment = _Alignment(alignment)
    if line_width is None:
        pango_width = -1
    else:
        pango_width = line_width / FRAME_WIDTH * DEFAULT_PIXEL_WIDTH

    # Write the result to a temporary svg file, and return it's contents.
    temp_file = Path(tempfile.gettempdir(), hash_string(markup_str)).with_suffix(".svg")
    manimpango.MarkupUtils.text2svg(
        text=markup_str,
        font="",                     # Already handled
        slant="NORMAL",              # Already handled
        weight="NORMAL",             # Already handled
        size=1,                      # Already handled
        _=0,                         # Empty parameter
        disable_liga=False,
        file_name=str(temp_file),
        START_X=0,
        START_Y=0,
        width=DEFAULT_CANVAS_WIDTH,
        height=DEFAULT_CANVAS_HEIGHT,
        justify=justify,
        indent=indent,
        line_spacing=None,           # Already handled
        alignment=alignment,
        pango_width=pango_width
    )
    result = temp_file.read_text()
    os.remove(temp_file)
    return result


class MarkupText(StringMobject):
    # See https://docs.gtk.org/Pango/pango_markup.html
    MARKUP_TAGS = {
        "b": {"font_weight": "bold"},
        "big": {"font_size": "larger"},
        "i": {"font_style": "italic"},
        "s": {"strikethrough": "true"},
        "sub": {"baseline_shift": "subscript", "font_scale": "subscript"},
        "sup": {"baseline_shift": "superscript", "font_scale": "superscript"},
        "small": {"font_size": "smaller"},
        "tt": {"font_family": "monospace"},
        "u": {"underline": "single"},
    }
    MARKUP_ENTITY_DICT = {
        "<": "&lt;",
        ">": "&gt;",
        "&": "&amp;",
        "\"": "&quot;",
        "'": "&apos;"
    }

    def __init__(
        self,
        text: str,
        font_size: int = 48,
        height: float | None = None,
        justify: bool = False,
        indent: float = 0,
        alignment: str = "",
        line_width: float | None = None,
        font: str = "",
        slant: str = NORMAL,
        weight: str = NORMAL,
        gradient: Iterable[ManimColor] | None = None,
        line_spacing_height: float | None = None,
        text2color: dict = {},
        text2font: dict = {},
        text2gradient: dict = {},
        text2slant: dict = {},
        text2weight: dict = {},
        # For convenience, one can use shortened names
        lsh: float | None = None,  # Overrides line_spacing_height
        t2c: dict = {},  # Overrides text2color if nonempty
        t2f: dict = {},  # Overrides text2font if nonempty
        t2g: dict = {},  # Overrides text2gradient if nonempty
        t2s: dict = {},  # Overrides text2slant if nonempty
        t2w: dict = {},  # Overrides text2weight if nonempty
        global_config: dict = {},
        local_configs: dict = {},
        disable_ligatures: bool = True,
        isolate: Selector = re.compile(r"\w+", re.U),
        **kwargs
    ):
        text_config = manim_config.text
        self.text = text
        self.font_size = font_size
        self.justify = justify
        self.indent = indent
        self.alignment = alignment or text_config.alignment
        self.line_width = line_width
        self.font = font or text_config.font
        self.slant = slant
        self.weight = weight if weight != NORMAL else getattr(text_config, 'weight', NORMAL)

        self.lsh = line_spacing_height or lsh
        self.t2c = text2color or t2c
        self.t2f = text2font or t2f
        self.t2g = text2gradient or t2g
        self.t2s = text2slant or t2s
        self.t2w = text2weight or t2w

        self.global_config = global_config
        self.local_configs = local_configs
        self.disable_ligatures = disable_ligatures
        self.isolate = isolate

        super().__init__(text, height=height, **kwargs)

        if self.t2g:
            log.warning("""
                Manim currently cannot parse gradient from svg.
                Please set gradient via `set_color_by_gradient`.
            """)
        if gradient:
            self.set_color_by_gradient(*gradient)
        if self.t2c:
            self.set_color_by_text_to_color_map(self.t2c)
        if height is None:
            self.scale(TEXT_MOB_SCALE_FACTOR)

    def get_svg_string_by_content(self, content: str) -> str:
        self.content = content
        return markup_to_svg(
            content,
            justify=self.justify,
            indent=self.indent,
            alignment=self.alignment,
            line_width=self.line_width
        )

    # Toolkits

    @staticmethod
    def escape_markup_char(substr: str) -> str:
        return MarkupText.MARKUP_ENTITY_DICT.get(substr, substr)

    @staticmethod
    def unescape_markup_char(substr: str) -> str:
        return {
            v: k
            for k, v in MarkupText.MARKUP_ENTITY_DICT.items()
        }.get(substr, substr)

    # Parsing

    @staticmethod
    def get_command_matches(string: str) -> list[re.Match]:
        pattern = re.compile(r"""
            (?P<tag>
                <
                (?P<close_slash>/)?
                (?P<tag_name>\w+)\s*
                (?P<attr_list>(?:\w+\s*\=\s*(?P<quot>["']).*?(?P=quot)\s*)*)
                (?P<elision_slash>/)?
                >
            )
            |(?P<passthrough>
                <\?.*?\?>|<!--.*?-->|<!\[CDATA\[.*?\]\]>|<!DOCTYPE.*?>
            )
            |(?P<entity>&(?P<unicode>\#(?P<hex>x)?)?(?P<content>.*?);)
            |(?P<char>[>"'])
        """, flags=re.X | re.S)
        return list(pattern.finditer(string))

    @staticmethod
    def get_command_flag(match_obj: re.Match) -> int:
        if match_obj.group("tag"):
            if match_obj.group("close_slash"):
                return -1
            if not match_obj.group("elision_slash"):
                return 1
        return 0

    @staticmethod
    def replace_for_content(match_obj: re.Match) -> str:
        if match_obj.group("tag"):
            return ""
        if match_obj.group("char"):
            return MarkupText.escape_markup_char(match_obj.group("char"))
        return match_obj.group()

    @staticmethod
    def replace_for_matching(match_obj: re.Match) -> str:
        if match_obj.group("tag") or match_obj.group("passthrough"):
            return ""
        if match_obj.group("entity"):
            if match_obj.group("unicode"):
                base = 10
                if match_obj.group("hex"):
                    base = 16
                return chr(int(match_obj.group("content"), base))
            return MarkupText.unescape_markup_char(match_obj.group("entity"))
        return match_obj.group()

    @staticmethod
    def get_attr_dict_from_command_pair(
        open_command: re.Match, close_command: re.Match
    ) -> dict[str, str] | None:
        pattern = r"""
            (?P<attr_name>\w+)
            \s*\=\s*
            (?P<quot>["'])(?P<attr_val>.*?)(?P=quot)
        """
        tag_name = open_command.group("tag_name")
        if tag_name == "span":
            return {
                match_obj.group("attr_name"): match_obj.group("attr_val")
                for match_obj in re.finditer(
                    pattern, open_command.group("attr_list"), re.S | re.X
                )
            }
        return MarkupText.MARKUP_TAGS.get(tag_name, {})

    def get_configured_items(self) -> list[tuple[Span, dict[str, str]]]:
        return [
            *(
                (span, {key: val})
                for t2x_dict, key in (
                    (self.t2c, "foreground"),
                    (self.t2f, "font_family"),
                    (self.t2s, "font_style"),
                    (self.t2w, "font_weight")
                )
                for selector, val in t2x_dict.items()
                for span in self.find_spans_by_selector(selector)
            ),
            *(
                (span, local_config)
                for selector, local_config in self.local_configs.items()
                for span in self.find_spans_by_selector(selector)
            )
        ]

    @staticmethod
    def get_command_string(
        attr_dict: dict[str, str], is_end: bool, label_hex: str | None
    ) -> str:
        if is_end:
            return "</span>"

        if label_hex is not None:
            converted_attr_dict = {"foreground": label_hex}
            for key, val in attr_dict.items():
                if key in (
                    "background", "bgcolor",
                    "underline_color", "overline_color", "strikethrough_color"
                ):
                    converted_attr_dict[key] = "black"
                elif key not in ("foreground", "fgcolor", "color"):
                    converted_attr_dict[key] = val
        else:
            converted_attr_dict = attr_dict.copy()
        attrs_str = " ".join([
            f"{key}='{val}'"
            for key, val in converted_attr_dict.items()
        ])
        return f"<span {attrs_str}>"

    def get_content_prefix_and_suffix(
        self, is_labelled: bool
    ) -> tuple[str, str]:
        global_attr_dict = {
            "foreground": color_to_hex(self.base_color),
            "font_family": self.font,
            "font_style": self.slant,
            "font_weight": self.weight,
            "font_size": str(round(self.font_size * 1024)),
        }
        # `line_height` attribute is supported since Pango 1.50.
        pango_version = manimpango.pango_version()
        if tuple(map(int, pango_version.split("."))) < (1, 50):
            if self.lsh is not None:
                log.warning(
                    "Pango version %s found (< 1.50), "
                    "unable to set `line_height` attribute",
                    pango_version
                )
        else:
            line_spacing_scale = self.lsh or DEFAULT_LINE_SPACING_SCALE
            global_attr_dict["line_height"] = str(
                ((line_spacing_scale) + 1) * 0.6
            )
        if self.disable_ligatures:
            global_attr_dict["font_features"] = "liga=0,dlig=0,clig=0,hlig=0"

        global_attr_dict.update(self.global_config)
        return tuple(
            self.get_command_string(
                global_attr_dict,
                is_end=is_end,
                label_hex=int_to_hex(0) if is_labelled else None
            )
            for is_end in (False, True)
        )

    # Method alias

    def get_parts_by_text(self, selector: Selector) -> VGroup:
        return self.select_parts(selector)

    def get_part_by_text(self, selector: Selector, **kwargs) -> VGroup:
        return self.select_part(selector, **kwargs)

    def set_color_by_text(self, selector: Selector, color: ManimColor):
        return self.set_parts_color(selector, color)

    def set_color_by_text_to_color_map(
        self, color_map: dict[Selector, ManimColor]
    ):
        return self.set_parts_color_by_dict(color_map)

    def get_text(self) -> str:
        return self.get_string()


class Code(MarkupText):
    def __init__(
        self,
        code: str,
        font: str = "Consolas",
        font_size: int = 24,
        lsh: float = 1.0,
        fill_color: ManimColor = None,
        stroke_color: ManimColor = None,
        language: str = "python",
        # Visit https://pygments.org/demo/ to have a preview of more styles.
        code_style: str = "monokai",
        **kwargs
    ):
        lexer = pygments.lexers.get_lexer_by_name(language)
        formatter = pygments.formatters.PangoMarkupFormatter(
            style=code_style
        )
        markup = pygments.highlight(code, lexer, formatter)
        markup = re.sub(r"</?tt>", "", markup)
        super().__init__(
            markup,
            font=font,
            font_size=font_size,
            lsh=lsh,
            stroke_color=stroke_color,
            fill_color=fill_color,
            **kwargs
        )


@contextmanager
def register_font(font_file: str | Path):
    """Temporarily add a font file to Pango's search path.
    This searches for the font_file at various places. The order it searches it described below.
    1. Absolute path.
    2. Downloads dir.

    Parameters
    ----------
    font_file :
        The font file to add.
    Examples
    --------
    Use ``with register_font(...)`` to add a font file to search
    path.
    .. code-block:: python
        with register_font("path/to/font_file.ttf"):
           a = Text("Hello", font="Custom Font Name")
    Raises
    ------
    FileNotFoundError:
        If the font doesn't exists.
    AttributeError:
        If this method is used on macOS.
    Notes
    -----
    This method of adding font files also works with :class:`CairoText`.
    .. important ::
        This method is available for macOS for ``ManimPango>=v0.2.3``. Using this
        method with previous releases will raise an :class:`AttributeError` on macOS.
    """

    file_path = Path(font_file).resolve()
    if not file_path.exists():
        error = f"Can't find {font_file}."
        raise FileNotFoundError(error)
    try:
        assert manimpango.register_font(str(file_path))
        yield
    finally:
        manimpango.unregister_font(str(file_path))
