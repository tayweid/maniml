"""A small, non-deserializing cache for generated text artifacts."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


class SafeTextCache:
    """Store UTF-8 strings without pickle or another executable format."""

    def __init__(self, directory: str | Path, size_limit: int) -> None:
        self.directory = Path(directory) / "text-v1"
        self.size_limit = int(size_limit)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path_for_key(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.directory / f"{digest}.txt"

    def get(self, key: str) -> str | None:
        path = self._path_for_key(key)
        try:
            value = path.read_text(encoding="utf-8")
            os.utime(path, None)
            return value
        except (OSError, UnicodeDecodeError):
            return None

    def set(self, key: str, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("SafeTextCache only accepts strings")

        target = self._path_for_key(key)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.directory,
                prefix=".tmp-",
                delete=False,
            ) as stream:
                temporary = stream.name
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary is not None:
                try:
                    Path(temporary).unlink()
                except FileNotFoundError:
                    pass

        self._prune()

    def clear(self) -> None:
        for path in self.directory.glob("*.txt"):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def _prune(self) -> None:
        entries: list[tuple[float, int, Path]] = []
        total = 0
        for path in self.directory.glob("*.txt"):
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            entries.append((stat.st_mtime, stat.st_size, path))
            total += stat.st_size

        for _mtime, size, path in sorted(entries):
            if total <= self.size_limit:
                break
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            total -= size
