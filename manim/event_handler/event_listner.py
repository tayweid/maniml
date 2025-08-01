from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable

    from manim.event_handler.event_type import EventType
    from manim.mobject.mobject import Mobject


class EventListener(object):
    def __init__(
        self,
        mobject: Mobject,
        event_type: EventType,
        event_callback: Callable[[Mobject, dict[str]]]
    ):
        self.mobject = mobject
        self.event_type = event_type
        self.callback = event_callback

    def __eq__(self, o: object) -> bool:
        return_val = False
        try:
            return_val = self.callback == o.callback \
                and self.mobject == o.mobject \
                and self.event_type == o.event_type
        except:
            pass
        return return_val
