#!/usr/bin/env python3
"""Drive a real --web scene and collect engine + socket-stage metrics."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

from websockets.sync.client import connect as ws_connect

from maniml.web.app import parse_viewer_launch_line


REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("scene")
    parser.add_argument("--renderer", choices=("gpu", "pixel", "split"),
                        default="gpu")
    parser.add_argument("--right-steps", type=int, default=1)
    parser.add_argument("--back-steps", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True,
                        help="Engine profile JSON; client summary sits beside it")
    parser.add_argument("--startup-timeout", type=float, default=40)
    parser.add_argument("--step-timeout", type=float, default=120)
    parser.add_argument(
        "--continuous-seconds", type=float, default=0,
        help="Collect each step for a fixed span instead of waiting for idle",
    )
    return parser.parse_args()


class Session:
    def __init__(self, args):
        self.args = args
        self.lines = []
        self.frames = []
        self.messages = []
        self.proc = None
        self.ws = None

    def start(self):
        source = self.args.source.resolve()
        profile = self.args.output.resolve()
        profile.parent.mkdir(parents=True, exist_ok=True)
        env = {
            **os.environ,
            "PYTHONPATH": str(REPO_ROOT),
            "PYTHONUNBUFFERED": "1",
            "MANIML_PERF_PATH": str(profile),
        }
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "maniml", str(source), self.args.scene,
             "--web", "--no-browser"],
            cwd=source.parent,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        threading.Thread(target=self._read_output, daemon=True).start()
        deadline = time.monotonic() + self.args.startup_timeout
        capability_url = None
        while time.monotonic() < deadline and capability_url is None:
            if self.proc.poll() is not None:
                raise RuntimeError("scene exited during startup:\n" + "".join(self.lines))
            capability_url = next(
                (url for line in self.lines
                 if (url := parse_viewer_launch_line(line))),
                None,
            )
            time.sleep(0.05)
        if capability_url is None:
            raise TimeoutError("viewer URL:\n" + "".join(self.lines))
        parsed = urlsplit(capability_url)
        origin = f"http://localhost:{parsed.port}"
        self.ws = ws_connect(
            f"ws://localhost:{parsed.port}/",
            origin=origin,
            max_size=2 ** 26,
            open_timeout=10,
        )
        ready = json.loads(self.ws.recv(timeout=5))
        if ready.get("type") != "ready":
            raise RuntimeError(f"unexpected handshake: {ready}")
        self.drain_until_quiet(maximum=10)

    def _read_output(self):
        for line in self.proc.stdout:
            self.lines.append(line)

    def set_renderer(self):
        geometry = self.args.renderer in {"gpu", "split"}
        pixels = self.args.renderer in {"pixel", "split"}
        self.ws.send(json.dumps({
            "type": "mode", "geometry": geometry, "pixels": pixels,
        }))
        if geometry:
            self.ws.send(json.dumps({"type": "geometry_request"}))
        self.drain_until_quiet(maximum=10)

    def key(self, key, **mods):
        self.ws.send(json.dumps({
            "type": "key", "action": "down", "key": key, **mods,
        }))
        self.ws.send(json.dumps({
            "type": "key", "action": "up", "key": key, **mods,
        }))
        if self.args.continuous_seconds:
            self.collect_for(self.args.continuous_seconds)
        else:
            self.drain_until_quiet(maximum=self.args.step_timeout)

    def collect_for(self, duration):
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            try:
                message = self.ws.recv(
                    timeout=max(0.05, deadline - time.monotonic()))
            except TimeoutError:
                return
            arrived = time.monotonic()
            if isinstance(message, bytes):
                self.frames.append({
                    "at": arrived,
                    "kind": {1: "jpeg", 2: "png", 3: "geometry"}.get(
                        message[0], f"binary-{message[0]}"),
                    "bytes": len(message),
                })
            else:
                payload = json.loads(message)
                if payload.get("type") != "log":
                    self.messages.append(payload)

    def drain_until_quiet(self, maximum, quiet=0.35):
        deadline = time.monotonic() + maximum
        while time.monotonic() < deadline:
            try:
                message = self.ws.recv(timeout=min(quiet, deadline - time.monotonic()))
            except TimeoutError:
                return
            arrived = time.monotonic()
            if isinstance(message, bytes):
                self.frames.append({
                    "at": arrived,
                    "kind": {1: "jpeg", 2: "png", 3: "geometry"}.get(
                        message[0], f"binary-{message[0]}"),
                    "bytes": len(message),
                })
            else:
                payload = json.loads(message)
                if payload.get("type") != "log":
                    self.messages.append(payload)
        raise TimeoutError("scene did not settle:\n" + "".join(self.lines[-80:]))

    def stop(self):
        quit_sent = False
        if self.ws is not None:
            try:
                self.ws.send(json.dumps({
                    "type": "key", "action": "down", "key": "q",
                    "meta": True,
                }))
                self.ws.send(json.dumps({
                    "type": "key", "action": "up", "key": "q",
                    "meta": True,
                }))
                quit_sent = True
            except Exception:
                pass
        if self.proc is not None and quit_sent:
            try:
                # Keep the client attached until the scene thread drains the
                # quit event; closing first parks the detached engine before
                # it can see the command.
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                self.proc.wait(timeout=5)

    def client_summary(self):
        by_kind = {}
        for kind in sorted({frame["kind"] for frame in self.frames}):
            frames = [frame for frame in self.frames if frame["kind"] == kind]
            intervals = [
                (right["at"] - left["at"]) * 1000
                for left, right in zip(frames, frames[1:])
            ]
            by_kind[kind] = {
                "count": len(frames),
                "bytes": sum(frame["bytes"] for frame in frames),
                "arrival_interval_p50_ms": percentile(intervals, 0.50),
                "arrival_interval_p95_ms": percentile(intervals, 0.95),
            }
        states = [message for message in self.messages
                  if message.get("type") == "state"]
        return {
            "format": 1,
            "renderer_requested": self.args.renderer,
            "frames": by_kind,
            "renderer_fallbacks": sum(
                message.get("type") == "renderer_fallback"
                for message in self.messages),
            "last_state": states[-1] if states else None,
            "stdout_tail": self.lines[-80:],
        }


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def main():
    args = parse_args()
    session = Session(args)
    try:
        session.start()
        session.set_renderer()
        for _ in range(args.right_steps):
            session.key("ArrowRight")
        for _ in range(args.back_steps):
            session.key("ArrowDown")
        # Revisit the retained endpoints just traversed. RIGHT before the
        # frontier must restore checkpoints, never execute source.
        for _ in range(args.back_steps):
            session.key("ArrowRight")
    finally:
        session.stop()
        client_path = args.output.with_name(args.output.stem + "-client.json")
        client_path.write_text(json.dumps(
            session.client_summary(), indent=2, sort_keys=True))
    if session.proc.returncode:
        raise SystemExit(
            f"scene exited {session.proc.returncode}:\n" + "".join(session.lines[-80:]))


if __name__ == "__main__":
    main()
