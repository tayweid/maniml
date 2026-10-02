import logging

__all__ = ["log"]


# A plain handler: the console panel in the viewer shows this output, and
# rich's terminal rendering (and its 2 MB) served a terminal nobody uses.
FORMAT = "%(levelname)s %(message)s"
logging.basicConfig(level=logging.WARNING, format=FORMAT, datefmt="[%X]")

log = logging.getLogger("manimgl")
