"""Cross-platform subprocess-group creation and bounded tree cleanup."""

from __future__ import annotations

import os
import signal
import subprocess
import time

PROCESS_TERMINATE_TIMEOUT = 3.0
PROCESS_KILL_TIMEOUT = 2.0
PROCESS_POLL_INTERVAL = 0.05


def process_group_popen_kwargs(platform: str | None = None) -> dict:
    """Return Popen options that isolate a child and everything it launches."""
    platform = platform or os.name
    if platform == "nt":
        return {
            "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        }
    return {"start_new_session": True}


def _process_group_exists(group_id: int) -> bool:
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _wait_for_process_group_exit(process, group_id: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        process.poll()  # reap the group leader as soon as it exits
        if not _process_group_exists(group_id):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(PROCESS_POLL_INTERVAL, remaining))


def _terminate_posix_process_tree(
    process,
    terminate_timeout: float,
    kill_timeout: float,
) -> None:
    group_id = process.pid
    try:
        os.killpg(group_id, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError:
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    if not _wait_for_process_group_exit(process, group_id, terminate_timeout):
        try:
            os.killpg(group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
        _wait_for_process_group_exit(process, group_id, kill_timeout)

    try:
        process.wait(timeout=kill_timeout)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=kill_timeout)
        except subprocess.TimeoutExpired:
            pass


def _run_taskkill(process_id: int, *, force: bool, timeout: float) -> bool:
    command = ["taskkill", "/PID", str(process_id), "/T"]
    if force:
        command.append("/F")
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _terminate_windows_process_tree(
    process,
    terminate_timeout: float,
    kill_timeout: float,
) -> None:
    if process.poll() is None:
        if not _run_taskkill(process.pid, force=False, timeout=terminate_timeout):
            try:
                process.terminate()
            except OSError:
                pass
        try:
            process.wait(timeout=terminate_timeout)
        except subprocess.TimeoutExpired:
            pass

    if process.poll() is None:
        if not _run_taskkill(process.pid, force=True, timeout=kill_timeout):
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=kill_timeout)
        except subprocess.TimeoutExpired:
            pass


def terminate_process_tree(
    process,
    *,
    platform: str | None = None,
    terminate_timeout: float = PROCESS_TERMINATE_TIMEOUT,
    kill_timeout: float = PROCESS_KILL_TIMEOUT,
) -> None:
    """Terminate a process group, escalating after bounded grace periods."""
    platform = platform or os.name
    if platform == "nt":
        _terminate_windows_process_tree(process, terminate_timeout, kill_timeout)
    else:
        _terminate_posix_process_tree(process, terminate_timeout, kill_timeout)
