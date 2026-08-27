"""Shadow semantic revisions for the measured performance migration.

This module is deliberately observational.  Legacy ``SceneState`` checkpoints
and the current renderers remain authoritative; setting
``MANIML_SHADOW_REVISIONS=1`` only assigns internal semantic identities and
records compact commit deltas beside them.  It is the parity/overhead lane for
the conditional structural-sharing and renderer-resource work, not a second
live engine.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import itertools
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable

import numpy as np

from maniml.performance import performance


SEMANTIC_ID_ATTR = "_maniml_semantic_id"
REVISION_DIRTY_ATTR = "_maniml_revision_dirty_components"
_NEXT_SEMANTIC_ID = itertools.count(1)
DEFAULT_SHADOW_RESOURCE_BUDGET = 64 * 1024 * 1024
DEFAULT_SHADOW_RESOURCE_CHUNK = 256 * 1024


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() not in {"0", "false", "no", "off"})


def semantic_id(mobject, *, assign: bool = True) -> int | None:
    """Return a process-unique semantic ID, assigning one when requested."""
    value = getattr(mobject, SEMANTIC_ID_ATTR, None)
    if value is None and assign:
        value = next(_NEXT_SEMANTIC_ID)
        setattr(mobject, SEMANTIC_ID_ATTR, value)
    return value


def forget_semantic_ids(mobject) -> None:
    """Give a public Mobject copy fresh identity on its next observation.

    Checkpoint snapshots use ``copy.deepcopy`` directly and therefore retain
    IDs.  Public ``Mobject.copy()`` calls this helper because the result is a
    new authored object, even when all its initial state matches the source.
    """
    seen: set[int] = set()
    stack = [mobject]
    while stack:
        current = stack.pop()
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        current.__dict__.pop(SEMANTIC_ID_ATTR, None)
        current.__dict__.pop(REVISION_DIRTY_ATTR, None)
        stack.extend(getattr(current, "submobjects", ()))


def mark_revision_dirty(mobject, component: str) -> None:
    """Record a built-in mutation hint without enabling shadow mode globally."""
    if getattr(mobject, SEMANTIC_ID_ATTR, None) is None:
        return
    dirty = mobject.__dict__.setdefault(REVISION_DIRTY_ATTR, set())
    dirty.add(component)


def _hash_parts(*parts: bytes) -> str:
    digest = hashlib.blake2b(digest_size=16)
    for part in parts:
        digest.update(len(part).to_bytes(8, "little"))
        digest.update(part)
    return digest.hexdigest()


def _array_bytes(value: np.ndarray) -> bytes:
    array = np.ascontiguousarray(value)
    return b"|".join((
        repr(array.dtype.descr).encode(),
        repr(array.shape).encode(),
        array.tobytes(order="C"),
    ))


_DERIVED_DATA_FIELDS = frozenset({
    # Lazily populated from points for native/client rendering. A clean
    # renderer pass may fill these caches on every VMobject; treating that as
    # semantic mutation would mark an entire batch dirty after one draw.
    "joint_angle",
    "base_normal",
})


def _semantic_data_components(mobject, value: np.ndarray) -> tuple[bytes, bytes]:
    names = value.dtype.names
    if not names:
        return _array_bytes(value), b""
    pointlike = set(getattr(mobject, "pointlike_data_keys", ("point",)))
    geometry = []
    style = []
    for name in names:
        if name in _DERIVED_DATA_FIELDS:
            continue
        encoded = name.encode() + _array_bytes(value[name])
        if (name in pointlike or "point" in name or "normal" in name):
            geometry.append(encoded)
        elif any(token in name for token in ("rgba", "color", "width", "opacity")):
            style.append(encoded)
        else:
            # Unknown payloads stay conservative: a missed geometry change is
            # worse than a broad geometry revision in the shadow lane.
            geometry.append(encoded)
    return b"".join(geometry), b"".join(style)


def _stable_bytes(value: Any) -> bytes:
    """Conservative stable encoding for renderer/config component hashes."""
    if isinstance(value, np.ndarray):
        return b"array:" + _array_bytes(value)
    if isinstance(value, np.generic):
        return b"scalar:" + repr(value.item()).encode()
    if isinstance(value, dict):
        parts = []
        for key in sorted(value, key=lambda item: repr(item)):
            parts.append(_stable_bytes(key))
            parts.append(_stable_bytes(value[key]))
        return b"dict:" + b"".join(parts)
    if isinstance(value, (list, tuple)):
        return b"seq:" + b"".join(_stable_bytes(item) for item in value)
    if isinstance(value, (str, bytes, int, float, bool, type(None))):
        return (type(value).__name__ + ":" + repr(value)).encode()
    return (type(value).__module__ + "." + type(value).__qualname__).encode()


def _updater_bytes(updaters: Iterable) -> bytes:
    parts = []
    for updater in updaters:
        function = getattr(updater, "__func__", updater)
        code = getattr(function, "__code__", None)
        parts.append(_stable_bytes((
            getattr(function, "__module__", ""),
            getattr(function, "__qualname__", type(function).__qualname__),
            getattr(code, "co_code", b""),
        )))
    return b"".join(parts)


def _family(mobjects: Iterable) -> list:
    result = []
    seen: set[int] = set()
    stack = list(reversed(list(mobjects)))
    while stack:
        mobject = stack.pop()
        marker = id(mobject)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(mobject)
        stack.extend(reversed(getattr(mobject, "submobjects", ())))
    return result


def _component_payloads(mobject) -> dict[str, bytes]:
    child_ids = tuple(
        semantic_id(child) for child in getattr(mobject, "submobjects", ()))
    data = getattr(mobject, "data", np.empty(0))
    geometry_data, style_data = _semantic_data_components(mobject, data)
    uniforms = getattr(mobject, "uniforms", {})
    return {
        "geometry": geometry_data,
        "style": style_data,
        "uniforms": _stable_bytes(uniforms),
        "family": _stable_bytes(child_ids),
        "renderer": _stable_bytes((
            type(mobject).__module__, type(mobject).__qualname__,
            getattr(mobject, "shader_folder", ""),
            getattr(mobject, "render_primitive", None),
            getattr(mobject, "depth_test", False),
            getattr(mobject, "z_index", 0),
            getattr(mobject, "is_fixed_in_frame", lambda: False)(),
        )),
        "texture": _stable_bytes(getattr(mobject, "texture_paths", None)),
        "updaters": _updater_bytes(getattr(mobject, "updaters", ())),
    }


def _component_hashes(mobject) -> dict[str, str]:
    return {
        name: _hash_parts(payload)
        for name, payload in _component_payloads(mobject).items()
    }


@dataclass(frozen=True)
class ObjectRevision:
    semantic_id: int
    revision: int
    components: dict[str, str]
    component_sizes: dict[str, int]
    component_resources: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class ResourceRef:
    semantic_id: int
    component: str
    resource_id: str
    byte_size: int
    chunk: int
    chunks: int
    new: bool

    def as_dict(self) -> dict:
        return {
            "semantic_id": self.semantic_id,
            "component": self.component,
            "resource_id": self.resource_id,
            "byte_size": self.byte_size,
            "chunk": self.chunk,
            "chunks": self.chunks,
            "new": self.new,
        }


@dataclass(frozen=True)
class CommitRecord:
    checkpoint: int
    reason: str
    scene_order: tuple[int, ...]
    added: tuple[int, ...]
    removed: tuple[int, ...]
    changed: dict[int, tuple[str, ...]]
    dirty_hints: dict[int, tuple[str, ...]]
    missed_hints: tuple[int, ...]
    extra_hints: tuple[int, ...]
    resource_refs: tuple[ResourceRef, ...]
    new_resource_bytes: int
    object_revisions: dict[int, int]
    camera: str
    camera_changed: bool

    def as_dict(self) -> dict:
        return {
            "checkpoint": self.checkpoint,
            "reason": self.reason,
            "scene_order": list(self.scene_order),
            "added": list(self.added),
            "removed": list(self.removed),
            "changed": {str(key): list(value) for key, value in self.changed.items()},
            "dirty_hints": {
                str(key): list(value) for key, value in self.dirty_hints.items()
            },
            "missed_hints": list(self.missed_hints),
            "extra_hints": list(self.extra_hints),
            "resource_refs": [ref.as_dict() for ref in self.resource_refs],
            "new_resource_bytes": self.new_resource_bytes,
            "object_revisions": {
                str(key): value for key, value in self.object_revisions.items()
            },
            "camera": self.camera,
            "camera_changed": self.camera_changed,
        }


class ShadowRevisionStore:
    """Compact semantic deltas, disabled unless explicitly requested."""

    def __init__(
        self,
        enabled: bool = False,
        path: str | os.PathLike | None = None,
        resource_budget_bytes: int = DEFAULT_SHADOW_RESOURCE_BUDGET,
        resource_chunk_bytes: int = DEFAULT_SHADOW_RESOURCE_CHUNK,
    ):
        self.enabled = enabled
        self.path = Path(path).expanduser() if path else None
        self.resource_budget_bytes = max(0, int(resource_budget_bytes))
        self.resource_chunk_bytes = max(1, int(resource_chunk_bytes))
        self.objects: dict[int, ObjectRevision] = {}
        self.commits: list[CommitRecord] = []
        # Dict shells are per checkpoint; immutable ObjectRevision values are
        # shared until an object changes. This is shadow metadata, not yet the
        # authoritative structural-sharing scene store.
        self._states_by_checkpoint: dict[int, dict[int, ObjectRevision]] = {}
        self.resources: dict[str, bytes] = {}
        self.validation_failures: list[dict] = []

    @classmethod
    def from_environment(cls) -> "ShadowRevisionStore":
        raw_budget = os.environ.get("MANIML_SHADOW_RESOURCE_BUDGET_BYTES")
        raw_chunk = os.environ.get("MANIML_SHADOW_RESOURCE_CHUNK_BYTES")
        try:
            budget = (
                int(raw_budget)
                if raw_budget is not None
                else DEFAULT_SHADOW_RESOURCE_BUDGET
            )
        except ValueError:
            budget = DEFAULT_SHADOW_RESOURCE_BUDGET
        try:
            chunk = (
                int(raw_chunk)
                if raw_chunk is not None
                else DEFAULT_SHADOW_RESOURCE_CHUNK
            )
        except ValueError:
            chunk = DEFAULT_SHADOW_RESOURCE_CHUNK
        return cls(
            enabled=_truthy(os.environ.get("MANIML_SHADOW_REVISIONS")),
            path=os.environ.get("MANIML_SHADOW_REVISIONS_PATH"),
            resource_budget_bytes=budget,
            resource_chunk_bytes=chunk,
        )

    def reset(self) -> None:
        if not self.enabled:
            return
        self.objects.clear()
        self.commits.clear()
        self._states_by_checkpoint.clear()
        self.resources.clear()
        self.validation_failures.clear()
        self._flush()

    def invalidate_after(self, checkpoint: int) -> None:
        if not self.enabled:
            return
        self.commits = [
            commit for commit in self.commits if commit.checkpoint <= checkpoint
        ]
        self._states_by_checkpoint = {
            index: state for index, state in self._states_by_checkpoint.items()
            if index <= checkpoint
        }
        self.objects = dict(self._states_by_checkpoint.get(checkpoint, {}))
        referenced = {
            resource_id
            for state in self._states_by_checkpoint.values()
            for revision in state.values()
            for resource_ids in revision.component_resources.values()
            for resource_id in resource_ids
        }
        self.resources = {
            resource_id: payload
            for resource_id, payload in self.resources.items()
            if resource_id in referenced
        }

    def prepare(self, scene) -> None:
        """Assign IDs before the authoritative checkpoint deepcopy."""
        if not self.enabled:
            return
        for mobject in _family(scene.mobjects):
            semantic_id(mobject)

    def commit(self, scene, checkpoint: int, *, reason: str) -> CommitRecord | None:
        if not self.enabled:
            return None
        with performance.stage("revision.shadow_commit"):
            if self.commits and checkpoint <= self.commits[-1].checkpoint:
                self.invalidate_after(checkpoint - 1)

            top_level = list(scene.mobjects)
            family = _family(top_level)
            current: dict[int, ObjectRevision] = {}
            payloads_by_object: dict[int, dict[str, bytes]] = {}
            changed: dict[int, tuple[str, ...]] = {}
            dirty_hints = {
                semantic_id(mobject): tuple(sorted(
                    getattr(mobject, REVISION_DIRTY_ATTR, ())))
                for mobject in family
                if getattr(mobject, REVISION_DIRTY_ATTR, None)
            }
            added = []
            for mobject in family:
                object_id = semantic_id(mobject)
                assert object_id is not None
                payloads = _component_payloads(mobject)
                components = {
                    name: _hash_parts(payload)
                    for name, payload in payloads.items()
                }
                component_sizes = {
                    name: len(payload) for name, payload in payloads.items()
                }
                component_resources = {
                    name: tuple(
                        _hash_parts(payload[offset:offset + self.resource_chunk_bytes])
                        for offset in range(
                            0, max(1, len(payload)), self.resource_chunk_bytes
                        )
                    )
                    for name, payload in payloads.items()
                }
                payloads_by_object[object_id] = payloads
                previous = self.objects.get(object_id)
                if previous is None:
                    revision = 1
                    added.append(object_id)
                    changed[object_id] = tuple(components)
                else:
                    delta = tuple(
                        name for name, digest in components.items()
                        if previous.components.get(name) != digest
                    )
                    revision = previous.revision + bool(delta)
                    if delta:
                        changed[object_id] = delta
                if previous is not None and not delta:
                    current[object_id] = previous
                else:
                    current[object_id] = ObjectRevision(
                        object_id,
                        int(revision),
                        components,
                        component_sizes,
                        component_resources,
                    )

            removed = tuple(sorted(set(self.objects) - set(current)))
            known_changes = set(changed) - set(added)
            missed_hints = tuple(sorted(known_changes - set(dirty_hints)))
            extra_hints = tuple(sorted(set(dirty_hints) - known_changes))
            resource_refs = []
            new_resource_bytes = 0
            for object_id, component_names in changed.items():
                revision = current[object_id]
                for component in component_names:
                    payload = payloads_by_object[object_id][component]
                    resource_ids = revision.component_resources[component]
                    for chunk_index, resource_id in enumerate(resource_ids):
                        offset = chunk_index * self.resource_chunk_bytes
                        chunk_payload = payload[
                            offset:offset + self.resource_chunk_bytes]
                        is_new = resource_id not in self.resources
                        if is_new:
                            self.resources[resource_id] = chunk_payload
                            new_resource_bytes += len(chunk_payload)
                        resource_refs.append(ResourceRef(
                            object_id,
                            component,
                            resource_id,
                            len(chunk_payload),
                            chunk_index,
                            len(resource_ids),
                            is_new,
                        ))
            camera = _hash_parts(_stable_bytes((
                getattr(scene.camera, "background_rgba", None),
                getattr(scene.camera, "fps", None),
                getattr(scene.camera, "pixel_width", None),
                getattr(scene.camera, "pixel_height", None),
            )))
            camera_changed = not self.commits or self.commits[-1].camera != camera
            record = CommitRecord(
                checkpoint=checkpoint,
                reason=reason,
                scene_order=tuple(semantic_id(mobject) for mobject in top_level),
                added=tuple(added),
                removed=removed,
                changed=changed,
                dirty_hints=dirty_hints,
                missed_hints=missed_hints,
                extra_hints=extra_hints,
                resource_refs=tuple(resource_refs),
                new_resource_bytes=new_resource_bytes,
                object_revisions={
                    key: value.revision for key, value in current.items()
                },
                camera=camera,
                camera_changed=camera_changed,
            )
            self.objects = current
            self.commits.append(record)
            self._states_by_checkpoint[checkpoint] = dict(current)
            history_object_refs = sum(
                len(state) for state in self._states_by_checkpoint.values())
            unique_object_revisions = len({
                id(revision)
                for state in self._states_by_checkpoint.values()
                for revision in state.values()
            })
            performance.increment("revision.shadow_commits")
            performance.gauge("revision.objects", len(current))
            performance.gauge("revision.changed_objects", len(changed))
            performance.gauge("revision.dirty_hints", len(dirty_hints))
            resource_bytes = sum(map(len, self.resources.values()))
            performance.gauge("revision.resource_bytes", resource_bytes)
            performance.gauge(
                "revision.resource_over_budget_bytes",
                max(0, resource_bytes - self.resource_budget_bytes),
            )
            performance.increment("revision.new_resource_bytes", new_resource_bytes)
            performance.increment("revision.missed_dirty_hints", len(missed_hints))
            performance.gauge("revision.history_object_refs", history_object_refs)
            performance.gauge(
                "revision.unique_object_revisions", unique_object_revisions)
            for mobject in family:
                mobject.__dict__.pop(REVISION_DIRTY_ATTR, None)
        # Optional diagnostics are I/O, not semantic observation cost.
        self._flush()
        return record

    def validate_checkpoint(self, scene_state, record: CommitRecord | None) -> bool:
        """Compare the authoritative copied endpoint with its live shadow."""
        if not self.enabled or record is None:
            return True
        with performance.stage("revision.shadow_validate"):
            copied = _family(scene_state.mobjects)
            copied_map = {
                semantic_id(mobject, assign=False): _component_hashes(mobject)
                for mobject in copied
            }
            expected = {
                key: value.components for key, value in self.objects.items()
            }
            resources_ok = all(
                all(
                    resource_id in self.resources
                    and _hash_parts(self.resources[resource_id]) == resource_id
                    for resource_id in resource_ids
                )
                and _hash_parts(b"".join(
                    self.resources[resource_id] for resource_id in resource_ids
                )) == revision.components[component]
                for revision in self.objects.values()
                for component, resource_ids in revision.component_resources.items()
            )
            ok = None not in copied_map and copied_map == expected and resources_ok
        if not ok:
            failure = {
                "checkpoint": record.checkpoint,
                "expected_ids": sorted(expected),
                "copied_ids": sorted(key for key in copied_map if key is not None),
            }
            self.validation_failures.append(failure)
            performance.increment("revision.validation_failures")
            self._flush()
        return ok

    def snapshot(self) -> dict:
        history_object_refs = sum(
            len(state) for state in self._states_by_checkpoint.values())
        unique_object_revisions = len({
            id(revision)
            for state in self._states_by_checkpoint.values()
            for revision in state.values()
        })
        return {
            "format": 1,
            "enabled": self.enabled,
            "resources": {
                "count": len(self.resources),
                "bytes": sum(map(len, self.resources.values())),
                "budget_bytes": self.resource_budget_bytes,
                "chunk_bytes": self.resource_chunk_bytes,
                "over_budget_bytes": max(
                    0,
                    sum(map(len, self.resources.values()))
                    - self.resource_budget_bytes,
                ),
            },
            "history": {
                "checkpoints": len(self._states_by_checkpoint),
                "object_refs": history_object_refs,
                "unique_object_revisions": unique_object_revisions,
                "shared_object_refs": max(
                    0, history_object_refs - unique_object_revisions),
            },
            "commits": [commit.as_dict() for commit in self.commits],
            "validation_failures": list(self.validation_failures),
        }

    def _flush(self) -> None:
        if not (self.enabled and self.path):
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(handle, "w") as stream:
                json.dump(self.snapshot(), stream, indent=2, sort_keys=True)
                stream.write("\n")
            os.replace(temporary, self.path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
