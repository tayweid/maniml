"""CE-compatible Table.

Mirrors ManimCE's ``manim.mobject.table.Table`` (see ``../manimce``): entries
are arranged on a fixed grid, labels join the grid as an extra first row and
column, and the separator lines are drawn midway between neighbouring rows
and columns. Only the CE features with a maniml counterpart are implemented;
``MathTable`` is the usual convenience subclass.
"""

from __future__ import annotations

import itertools as it

from maniml.constants import BLACK
from maniml.mobject.ce_shapes import Paragraph
from maniml.mobject.geometry import Line
from maniml.mobject.shape_matchers import BackgroundRectangle
from maniml.mobject.svg.tex_mobject import MathTex
from maniml.mobject.types.vectorized_mobject import VGroup, VMobject

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable, Iterable, Sequence
    from maniml.typing import ManimColor


class Table(VGroup):
    def __init__(
        self,
        table: Sequence[Sequence[float | str | VMobject]],
        row_labels: Iterable[VMobject] | None = None,
        col_labels: Iterable[VMobject] | None = None,
        top_left_entry: VMobject | None = None,
        v_buff: float = 0.8,
        h_buff: float = 1.3,
        include_outer_lines: bool = False,
        add_background_rectangles_to_entries: bool = False,
        entries_background_color: ManimColor = BLACK,
        include_background_rectangle: bool = False,
        background_rectangle_color: ManimColor = BLACK,
        element_to_mobject: Callable[..., VMobject] = Paragraph,
        element_to_mobject_config: dict = {},
        arrange_in_grid_config: dict = {},
        line_config: dict = {},
        **kwargs,
    ):
        self.row_labels = list(row_labels) if row_labels is not None else None
        self.col_labels = list(col_labels) if col_labels is not None else None
        self.top_left_entry = top_left_entry
        self.row_dim = len(table)
        self.col_dim = len(table[0])
        self.v_buff = v_buff
        self.h_buff = h_buff
        self.include_outer_lines = include_outer_lines
        self.element_to_mobject = element_to_mobject
        self.element_to_mobject_config = element_to_mobject_config
        self.arrange_in_grid_config = arrange_in_grid_config
        self.line_config = line_config

        for row in table:
            if len(row) != len(table[0]):
                raise ValueError("Not all rows in table have the same length.")

        super().__init__(**kwargs)
        mob_table = self._table_to_mob_table(table)
        self.elements_without_labels = VGroup(*it.chain(*mob_table))
        mob_table = self._add_labels(mob_table)
        self._organize_mob_table(mob_table)
        self.elements = VGroup(*it.chain(*mob_table))

        # Drop the invisible placeholder occupying the top-left cell, if any
        if not self.elements[0].has_points() and not self.elements[0].submobjects:
            self.elements.remove(self.elements[0])

        self.add(self.elements)
        self.center()
        self.mob_table = mob_table
        self._add_horizontal_lines()
        self._add_vertical_lines()
        if add_background_rectangles_to_entries:
            self.add_background_to_entries(color=entries_background_color)
        if include_background_rectangle:
            self.background_rectangle = BackgroundRectangle(
                self, color=background_rectangle_color, fill_opacity=0.5
            )
            self.add_to_back(self.background_rectangle)

    def _table_to_mob_table(self, table) -> list:
        return [
            [
                item if isinstance(item, VMobject)
                else self.element_to_mobject(str(item), **self.element_to_mobject_config)
                for item in row
            ]
            for row in table
        ]

    def _organize_mob_table(self, table) -> VGroup:
        help_table = VGroup()
        for row in table:
            help_table.add(*row)
        help_table.arrange_in_grid(
            n_rows=len(table),
            n_cols=len(table[0]),
            h_buff=self.h_buff,
            v_buff=self.v_buff,
            **self.arrange_in_grid_config,
        )
        return help_table

    def _add_labels(self, mob_table: list) -> list:
        if self.row_labels is not None:
            for k in range(len(self.row_labels)):
                mob_table[k] = [self.row_labels[k], *mob_table[k]]
        if self.col_labels is not None:
            if self.row_labels is not None:
                top_left = (
                    self.top_left_entry
                    if self.top_left_entry is not None
                    else VMobject()  # placeholder so the grid stays rectangular
                )
                mob_table.insert(0, [top_left, *self.col_labels])
            else:
                mob_table.insert(0, list(self.col_labels))
        return mob_table

    def _add_horizontal_lines(self) -> Table:
        anchor_left = self.get_left()[0] - 0.5 * self.h_buff
        anchor_right = self.get_right()[0] + 0.5 * self.h_buff
        rows = self.get_rows()
        line_group = VGroup()
        if self.include_outer_lines:
            for anchor in (
                rows[0].get_top()[1] + 0.5 * self.v_buff,
                rows[-1].get_bottom()[1] - 0.5 * self.v_buff,
            ):
                line = Line(
                    [anchor_left, anchor, 0], [anchor_right, anchor, 0],
                    **self.line_config,
                )
                line_group.add(line)
                self.add(line)
        for k in range(len(self.mob_table) - 1):
            anchor = 0.5 * (rows[k].get_bottom()[1] + rows[k + 1].get_top()[1])
            line = Line(
                [anchor_left, anchor, 0], [anchor_right, anchor, 0],
                **self.line_config,
            )
            line_group.add(line)
            self.add(line)
        self.horizontal_lines = line_group
        return self

    def _add_vertical_lines(self) -> Table:
        rows = self.get_rows()
        anchor_top = rows.get_top()[1] + 0.5 * self.v_buff
        anchor_bottom = rows.get_bottom()[1] - 0.5 * self.v_buff
        cols = self.get_columns()
        line_group = VGroup()
        if self.include_outer_lines:
            for anchor in (
                cols[0].get_left()[0] - 0.5 * self.h_buff,
                cols[-1].get_right()[0] + 0.5 * self.h_buff,
            ):
                line = Line(
                    [anchor, anchor_top, 0], [anchor, anchor_bottom, 0],
                    **self.line_config,
                )
                line_group.add(line)
                self.add(line)
        for k in range(len(self.mob_table[0]) - 1):
            anchor = 0.5 * (cols[k].get_right()[0] + cols[k + 1].get_left()[0])
            line = Line(
                [anchor, anchor_bottom, 0], [anchor, anchor_top, 0],
                **self.line_config,
            )
            line_group.add(line)
            self.add(line)
        self.vertical_lines = line_group
        return self

    def get_horizontal_lines(self) -> VGroup:
        return self.horizontal_lines

    def get_vertical_lines(self) -> VGroup:
        return self.vertical_lines

    def get_columns(self) -> VGroup:
        return VGroup(*(
            VGroup(*(row[i] for row in self.mob_table))
            for i in range(len(self.mob_table[0]))
        ))

    def get_rows(self) -> VGroup:
        return VGroup(*(VGroup(*row) for row in self.mob_table))

    def get_entries(self, pos: Sequence[int] | None = None) -> VMobject | VGroup:
        if pos is not None:
            return self.mob_table[pos[0] - 1][pos[1] - 1]
        return self.elements

    def get_entries_without_labels(self, pos: Sequence[int] | None = None):
        if pos is not None:
            index = self.col_dim * (pos[0] - 1) + pos[1] - 1
            return self.elements_without_labels[index]
        return self.elements_without_labels

    def get_row_labels(self) -> VGroup:
        return VGroup(*(self.row_labels or []))

    def get_col_labels(self) -> VGroup:
        return VGroup(*(self.col_labels or []))

    def get_labels(self) -> VGroup:
        label_mobs = [*(self.col_labels or []), *(self.row_labels or [])]
        if self.top_left_entry is not None:
            label_mobs.insert(0, self.top_left_entry)
        return VGroup(*label_mobs)

    def add_background_to_entries(self, color: ManimColor = BLACK) -> Table:
        for mob in self.get_entries():
            mob.add_background_rectangle(color=color)
        return self

    def set_column_colors(self, *colors) -> Table:
        for color, column in zip(colors, self.get_columns()):
            column.set_color(color)
        return self

    def set_row_colors(self, *colors) -> Table:
        for color, row in zip(colors, self.get_rows()):
            row.set_color(color)
        return self


class MathTable(Table):
    def __init__(self, table, element_to_mobject=MathTex, **kwargs):
        super().__init__(table, element_to_mobject=element_to_mobject, **kwargs)
