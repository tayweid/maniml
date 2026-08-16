from __future__ import annotations

import http.client
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING

import validators

from maniml.utils.simple_functions import hash_string

if TYPE_CHECKING:
    from typing import Iterable


REMOTE_ASSET_SOCKET_TIMEOUT = 15
REMOTE_ASSET_TOTAL_TIMEOUT = 60
REMOTE_ASSET_MAX_BYTES = 256 * 1024 * 1024
REMOTE_ASSET_CHUNK_BYTES = 1024 * 1024
_SAFE_SUFFIX = re.compile(r"\.[A-Za-z0-9]{1,10}\Z")


class RemoteAssetError(OSError):
    """Raised when a URL-backed image, vector, or sound cannot be fetched."""


def guarantee_existence(path: str | Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path.absolute()


def _get_downloads_dir() -> str:
    # Keep this import local: directories imports guarantee_existence from this
    # module, so a module-level import would make the two modules order-dependent.
    from maniml.utils.directories import get_downloads_dir

    downloads_dir: str = get_downloads_dir()
    return downloads_dir


def _remote_origin(url: str) -> str:
    """Identify a remote host without echoing credentials or signed URL data."""
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or "unknown host"
    try:
        port = parsed.port
    except ValueError:
        port = None
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if port is not None:
        host = f"{host}:{port}"
    return f"{parsed.scheme.lower()}://{host}"


def _remote_suffix(url: str) -> str:
    suffix = Path(urllib.parse.urlsplit(url).path).suffix
    return suffix if _SAFE_SUFFIX.fullmatch(suffix) else ""


def _size_description(size: int) -> str:
    return f"{size / (1024 * 1024):g} MiB"


def _download_remote_file(url: str) -> Path:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise RemoteAssetError(
            "Remote assets must use an http:// or https:// URL; "
            f"got {parsed.scheme or 'no'} scheme."
        )

    origin = _remote_origin(url)
    folder = guarantee_existence(_get_downloads_dir())
    file_hash: str = hash_string(url)
    path: Path = (folder / file_hash).with_suffix(_remote_suffix(url))
    if path.is_file():
        return path

    temporary_path: Path | None = None
    deadline = monotonic() + REMOTE_ASSET_TOTAL_TIMEOUT
    expected_size: int | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}-",
            suffix=".part",
            dir=folder,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            with urllib.request.urlopen(
                url, timeout=REMOTE_ASSET_SOCKET_TIMEOUT
            ) as response:
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        expected_size = int(content_length)
                    except ValueError:
                        expected_size = None
                    if (
                        expected_size is not None
                        and expected_size > REMOTE_ASSET_MAX_BYTES
                    ):
                        raise RemoteAssetError(
                            f"Remote asset from {origin} exceeds the "
                            f"{_size_description(REMOTE_ASSET_MAX_BYTES)} "
                            "download limit."
                        )

                downloaded = 0
                while True:
                    if monotonic() >= deadline:
                        raise RemoteAssetError(
                            f"Remote asset download from {origin} did not "
                            f"complete within {REMOTE_ASSET_TOTAL_TIMEOUT} seconds."
                        )
                    remaining = REMOTE_ASSET_MAX_BYTES - downloaded
                    chunk = response.read(min(REMOTE_ASSET_CHUNK_BYTES, remaining + 1))
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > REMOTE_ASSET_MAX_BYTES:
                        raise RemoteAssetError(
                            f"Remote asset from {origin} exceeds the "
                            f"{_size_description(REMOTE_ASSET_MAX_BYTES)} "
                            "download limit."
                        )
                    temporary_file.write(chunk)

                if expected_size is not None and downloaded != expected_size:
                    raise RemoteAssetError(
                        f"Remote asset download from {origin} was incomplete "
                        f"({downloaded} of {expected_size} bytes received)."
                    )
                if monotonic() >= deadline:
                    raise RemoteAssetError(
                        f"Remote asset download from {origin} did not complete "
                        f"within {REMOTE_ASSET_TOTAL_TIMEOUT} seconds."
                    )

            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.replace(temporary_path, path)
        temporary_path = None
        return path
    except RemoteAssetError:
        raise
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        raise RemoteAssetError(
            f"Remote asset request to {origin} failed with HTTP status {status}."
        ) from None
    except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):
            raise RemoteAssetError(
                f"Remote asset request to {origin} timed out after "
                f"{REMOTE_ASSET_SOCKET_TIMEOUT} seconds."
            ) from None
        raise RemoteAssetError(
            f"Remote asset request to {origin} failed with a "
            f"{type(error.reason).__name__} network error."
        ) from None
    except TimeoutError:
        raise RemoteAssetError(
            f"Remote asset request to {origin} timed out after "
            f"{REMOTE_ASSET_SOCKET_TIMEOUT} seconds."
        ) from None
    except http.client.HTTPException:
        raise RemoteAssetError(
            f"Remote asset request to {origin} returned an invalid or "
            "incomplete HTTP response."
        ) from None
    except OSError as error:
        raise RemoteAssetError(
            f"Could not download and cache remote asset from {origin}: {error}"
        ) from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def find_file(
    file_name: str,
    directories: Iterable[str] | None = None,
    extensions: Iterable[str] | None = None,
) -> Path:
    # URL assets share a local cache. A complete file is promoted into that
    # cache atomically, so interrupted downloads can never become cache hits.
    if validators.url(file_name):
        return _download_remote_file(file_name)

    # Check if what was passed in is already a valid path to a file
    if os.path.exists(file_name):
        return Path(file_name)

    # Otherwise look in local file system
    directories = directories or [""]
    extensions = extensions or [""]
    possible_paths = (
        Path(directory, file_name + extension)
        for directory in directories
        for extension in extensions
    )
    for path in possible_paths:
        if path.exists():
            return path
    raise IOError(f"{file_name} not Found")
