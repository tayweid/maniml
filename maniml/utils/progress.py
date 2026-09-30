"""A progress display that displays nothing.

tqdm drew a terminal bar around a render's frames and an SVG
triangulation. ManimLive is an app, not a terminal (Taylor, 2026-09-30):
the viewer shows what is happening, and a render's progress is a line in
its log. This keeps the shape the callers use (an iterable with a total,
`set_description`, `update`, `close`, and the keyword arguments tqdm
took) and prints nothing.
"""

from __future__ import annotations

from typing import Iterable, Iterator


class ProgressDisplay:
    def __init__(self, iterable: Iterable | None = None, total: int | None = None,
                 desc: str = "", **_ignored):
        self.iterable = iterable
        self.total = total
        self.desc = desc
        self.n = 0

    def __iter__(self) -> Iterator:
        if self.iterable is None:
            return iter(())
        for item in self.iterable:
            self.n += 1
            yield item

    def __len__(self) -> int:
        if self.total is not None:
            return self.total
        return len(self.iterable) if self.iterable is not None else 0

    def set_description(self, desc: str = "") -> None:
        self.desc = desc

    def update(self, n: int = 1) -> None:
        self.n += n

    def close(self) -> None:
        pass
