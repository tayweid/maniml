from __future__ import annotations

from collections.abc import Callable
from functools import wraps

from maniml.utils.directories import get_cache_dir
from maniml.utils.safe_text_cache import SafeTextCache
from maniml.utils.simple_functions import hash_string

CACHE_SIZE = 1_000_000_000  # 1 GB
_cache: SafeTextCache | None = None


def _get_cache() -> SafeTextCache:
    global _cache
    if _cache is None:
        _cache = SafeTextCache(get_cache_dir(), size_limit=CACHE_SIZE)
    return _cache


def cache_on_disk(func: Callable[..., str]) -> Callable[..., str]:
    @wraps(func)
    def wrapper(*args, **kwargs):
        key = hash_string(f"{func.__name__}{args}{kwargs}")
        try:
            cache = _get_cache()
        except OSError:
            return func(*args, **kwargs)
        value = cache.get(key)
        if value is None:
            value = func(*args, **kwargs)
            try:
                cache.set(key, value)
            except OSError:
                pass
        return value

    return wrapper


def clear_cache():
    _get_cache().clear()
