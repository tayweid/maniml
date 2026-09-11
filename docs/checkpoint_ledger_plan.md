# Plan: the checkpoint ledger

Implementation plan for TODO.md "Now" item 1, the stall at every play
boundary. Written 2026-09-05 against commit `d12a1421`. Design
background is in `../simlab/JANIM.md`; this document is the sequence,
the mechanism in detail, and the guards. Nothing here has shipped.

## The number to move

`checkpoint.save_copy` (`scene/checkpoints.py:386`) is the deep copy
of the scene state and the exec namespace at every `play`. The gate
review measured it at 22 ms p50 on the course scene; the boids run
shows 15 ms p50 and 54 ms max. The target is a static play (nothing
moved since the last checkpoint) costing under 2 ms, and a typical
play costing what moved.

## What the cost actually is

Measured 2026-09-05 in this venv (numpy 2.5, M3):

| Case | Objects | Array data | `copy.deepcopy` | `np.copy` of the arrays only |
| --- | ---: | ---: | ---: | ---: |
| 1,000 Squares in a VGroup | 1,001 | 650 KB | 27 ms | 1 ms |
| 1 Circle with 300k points | 1 | 13 MB | 0.4 ms | 1 ms |

The deep copy costs about 27 µs **per mobject** and is nearly
independent of array bytes. A Tex-heavy course scene is hundreds of
glyph mobjects, so the stall is Python object-graph traversal. Two
consequences drive the design:

- The only fix is to **not visit unchanged mobjects at all**. Trimming
  render-only state (TODO "copy less") lowers the per-object constant;
  it cannot remove the traversal.
- Cheap comparison is affordable as a *safety net*, not as the signal:
  field-wise `array_equal` of 1,000 squares against frozen copies is
  3.6 ms and blake2b of their data is 0.6 ms. The August revision
  store failed on correctness (missed writes, derived-column false
  positives), not on cost.

## The mechanism

**A checkpoint becomes a ledger entry.** `deepcopy_namespace` keeps
its shape: one `copy.deepcopy(must_copy, memo)` over the namespace and
the `SceneState` together, so variable-to-mobject identity and
`_rebind_functions` are untouched. The change is that the memo is
**pre-seeded** before the call: every live mobject that is *reusable*
maps to the frozen copy it got at an earlier checkpoint. `deepcopy`
then hands that copy back wherever the live object is reached (the
state list, a namespace variable, a parent's `submobjects`, a closure
cell) and never descends into it.

**The ledger** is a `weakref.WeakKeyDictionary` on the checkpoint
manager (Mobject has no `__eq__`, so identity hashing holds):
`live mobject -> (revision_at_freeze, frozen copy, reusable flag)`.
Entries die with their live object; a frozen copy lives as long as a
checkpoint or the ledger references it. Memory across checkpoints
drops from objects × checkpoints to objects + changes.

**The signal is a per-mobject `revision` counter**, bumped at the two
choke points that already exist, `note_changed_data` and
`note_changed_family` (`mobject/mobject.py:266`, `:478`). Both recurse
up `parents`, so a changed child bumps every ancestor, which is what
makes a parent's revision mean "nothing in my family changed". The
choke points cover every `affects_data` / `affects_family_data`
method, `interpolate`, `add` / `remove` / `set_submobjects` /
`replace_submobject` / `insert_submobject`, and the 35 explicit
`note_changed_data` calls in the geometry, VMobject, surface, image,
point-cloud and camera-frame files. Sites that change checkpoint-
relevant state *without* passing a choke point must bump explicitly;
the enumerated list from reading the code is:

- uniform writes: `set_uniform`, `set_uniforms`, `ValueTracker.set_value`
  (`value_tracker.py:44`, the important one), `CameraFrame` orientation
  and fovy (`camera_frame.py:54,220,225`), `DotCloud.set_glow_factor`,
  `VMobject.set_joint_type`, `Surface` `num_textures`, the clip-plane
  writes in `mobject.py:2016–2022`, and `interpolate`'s uniform lerp
  (`mobject.py:1888`, already under a `note_changed_data`);
- `add_updater` / `insert_updater` / `remove_updater` /
  `clear_updaters` / `match_updaters`, `suspend_updating` /
  `resume_updating`;
- `z_index`: it is a property, so the bump lives in its setter and
  covers `set_z_index` and every CE-style `mob.z_index = n` write;
- `generate_target`, `save_state`;
- `lock_data` / `unlock_data`, `set_animating_status`,
  `fix_in_frame` / `unfix_from_frame`, `apply_depth_test` /
  `deactivate_depth_test`, `set_color_by_code`
  (`shader_code_replacements`).

Derived columns that the render pass fills lazily — `joint_angle`,
`base_normal`, `d_normal_point` (`vectorized_mobject.py:898,1179`,
`surface.py:103`, `three_dimensions.py:115`) — set `_data_has_changed`
directly and never call `note_changed_data`, so they do **not** bump
the revision. That is the false-positive class the August attempt
fought, and here it is inert: a stale derived column in a frozen copy
is harmless because the copy's `_data_has_changed` flag makes the
render pass recompute it.

**The reuse rule follows references.** A frozen copy is immutable and
shared, so it cannot be re-pointed: if an unchanged mobject referenced
a *changed* one, reusing it would carry a stale reference into the new
checkpoint and the restore would drag the old object in — the ghost
class of bug. So an entry is reusable only when its revision is
unchanged **and** everything it reaches is reusable too: its
submobjects, and the mobjects behind its reference attributes
(`target`, `saved_state`, a `SurroundingRectangle.mobject`, any
attribute or one-level container holding a mobject), transitively. The
attribute names are recorded on the entry at freeze time, so the walk
costs a few dictionary reads per mobject. The one thing that makes a
copy unshareable outright is an updater: its closure holds mobjects
the walk cannot see. Mobjects with updaters change every frame anyway.
(The plan first said "leaf entries only: no target, no saved state".
That would have copied every mobject ever animated with `.animate`
forever, because `.animate` leaves `target` behind; the reference walk
replaced it before Phase 2 landed.) Children are additionally safe
because a child change bumps the parent's revision.

**Parents are stripped from frozen copies and rebuilt on restore.**
Mobject has no `__deepcopy__`, so a plain deep copy copies `parents`
through the memo. With sharing, an unchanged child reused under a
re-copied parent would keep a `parents` list pointing at the *previous*
checkpoint's parent, and a restore would deep-copy that orphan in and
route `note_changed_data` to it instead of the real parent — a stale
bounding box the user sees as a wrong `next_to`. Rule: **frozen graphs
have no parent links; live graphs do.** After the save-direction copy,
every newly created frozen mobject gets `parents = []`. After the
restore-direction copy (`restore_copy`, `execution_copy`,
`SceneState.copy`), walk the copied mobjects and append each one to
its submobjects' `parents`. This is also cleaner than today, which
follows parent links to objects outside the checkpoint (the render-
batch leak that `test_render_batches_are_not_checkpoint_parents`
guards against).

**Frozen copies are frozen.** After the save-direction copy, each new
frozen mobject's `data` and array uniforms get
`flags.writeable = False`. Nothing legitimately writes to history —
every restore deep-copies, and copies come back writeable (verified) —
so this turns "someone mutated a checkpoint" into an immediate
`ValueError` instead of a silent corruption. This is the *cheap* half
of the freeze idea, with no compatibility cost; freezing the *live*
arrays is the optional hardening step in Phase 4.

**The ledger is seeded on restore.** When a checkpoint is restored,
the memo maps each frozen mobject to its new live copy with the same
revision, so record `live -> (revision, frozen)` immediately. A play
after a step back then reuses everything untouched instead of
re-copying the whole scene once.

**`_rebind_functions` needs one guard.** Its final loop reassigns
`value.updaters` on every Mobject in `memo.values()`; reused frozen
entries are in there. Leaf entries have no updaters, so the loop is a
no-op on them today, but skip pre-seeded ids explicitly so a later
widening of the reuse rule cannot mutate shared history.

**Verify mode is the discovery tool.** `MANIML_VERIFY_LEDGER=1` makes
every reuse decision check itself: for each mobject about to be
reused, compare the live object against its frozen copy — `data`
field-wise excluding the derived columns, uniforms, submobject
identity through the memo, updater count, `z_index`, the lock sets,
`_is_animating`, and every plain-typed `__dict__` entry — and raise
`LedgerStale(mobject, attribute)` naming what differed. Any site that
mutates state without bumping the revision becomes a failing test that
names the attribute, which is the loud failure the freeze was meant to
provide, without the compatibility cost. It stays off in normal runs
because it costs about what the copy did.

## Phases

### Phase 0 — Baseline (half a day)

Run a real course episode (`../../econ-0100/Blocks/A3_Trade/03_Code.py`
or whichever stalls most) with `MANIML_PERF_PATH` set and record
`checkpoint.save_copy` p50/p95, `checkpoint.restore_copy`,
`animation.begin`, and the mobject count per checkpoint. Add three
counters now so the win is visible later: `checkpoint.ledger.reused`,
`checkpoint.ledger.copied`, `checkpoint.ledger.entries` (gauge).
Commit the numbers into this file.

*Measured 2026-09-05*, `EpisodeA3 --render` (62 plays, 112
checkpoints, latex present, the miniconda editable install):

| Stage | Count | p50 | p95 | Max |
| --- | ---: | ---: | ---: | ---: |
| `checkpoint.save_copy` | 112 | 192 ms | 933 ms | 2,898 ms |
| `checkpoint.execution_copy` (thaw before each unit) | 93 | 188 ms | 979 ms | 3,151 ms |
| `animation.begin` | 81 | 9 ms | 39 ms | 58 ms |
| `animation.finish` | 81 | 2 ms | 13 ms | 16 ms |

The real scene is an order of magnitude worse than the audit's 22 to
37 ms: every play pays about 0.2 s of copying at the median, and the
thaw before each unit (`execution_copy`, the deep copy of the stored
checkpoint that `run_next_animation` execs against) pays the same
again. The copy is the stall, not `begin_animations`.

**What the copy is made of** (a probe over all 93 checkpoints of the
same run, then a census of the final one):

- The namespace, not the screen. On-screen mobjects stay around 200
  (max 641) through the episode; the namespace grows from 31 variables
  to 122, and by the end all 94 of its mobject variables are off
  screen. Each one is still deep-copied at every play. The namespace
  half of the copy grows from 38 ms to several seconds across the
  episode while the state half stays at 25 to 50 ms. This is exactly
  what the ledger removes: an off-screen mobject never changes again.
- The final checkpoint visits 4,485 mobjects and 296,000 objects in
  one copy. Of those, roughly 200,000 are svgelements path objects
  (`Point`, `CubicBezier`, `Line`, `Move`, `Close`, `Path` and their
  dicts): every Tex glyph keeps its parsed `path_obj`, used only while
  building the points. A 25-glyph Tex deep-copies in 5.7 ms with it
  and 0.8 ms without. Sharing it by reference is the first "copy less"
  item and landed with Phase 1 (`Mobject.__deepcopy__` with a
  `_copy_by_reference` list; `VMobjectFromSVGPath` names `path_obj` and
  `transform_cache`).
- Dead parent links are not the growth driver here: cutting `parents`
  during the copy removed 66 of 4,485 mobjects. The rule to drop them
  from frozen graphs stands for correctness, not for speed.
- Array bytes are irrelevant: 10 MB in 32,000 arrays.

Same render after sharing the svg path (everything else unchanged):

| Stage | p50 | p95 | Max | Total over the episode |
| --- | ---: | ---: | ---: | ---: |
| `checkpoint.save_copy` | 192 → 46 ms | 933 → 112 ms | 2,898 → 1,010 ms | 33.3 → 7.8 s |
| `checkpoint.execution_copy` | 188 → 48 ms | 979 → 595 ms | 3,151 → 933 ms | 31.3 → 10.8 s |

A four-fold cut from one attribute. What remains is the per-object
traversal of the accumulated namespace, which is the ledger's job.

Same render again with the ledger (Phase 2) and the frontier skip
(Phase 2b, forward half):

| Run | Save p50 | Save p95 | Save max | Thaw p50 | Copy time over the episode |
| --- | ---: | ---: | ---: | ---: | ---: |
| Before | 192 ms | 933 ms | 2,898 ms | 188 ms | 64.6 s |
| Shared svg path | 46 ms | 112 ms | 1,010 ms | 48 ms | 18.6 s |
| + ledger | 9 ms | 34 ms | 135 ms | 80 ms | 12.5 s |
| + frontier skip | 10 ms | 30 ms | 111 ms | skipped, 92 of 93 | 1.3 s |

Over the episode the ledger reused 208,406 mobject copies and made
21,113. The remaining 10 ms median is the mobjects each play actually
moved plus the walk over the reusable ones (an integer compare and a
few dictionary reads per mobject; about 4,500 of them by the end).

Note `animation.begin` separately: the audit's 37 ms per play was
roughly 17 ms of `begin_animations` plus 19 ms of copy. This plan
removes the copy. If `begin` dominates on the course scene, that is a
different item (Transform alignment, `set_animating_status` family
walks) and should be split out rather than folded in.

### Phase 1 — Revision counter and the verify harness (one day)

- `Mobject.__init__`: `self.revision = 0`. Bump in `note_changed_data`
  and `note_changed_family` (one line each; they already recurse up).
- Explicit bumps at the enumerated sites above. Keep a
  `_bump_revision()` helper so the sites read as intent.
- `checkpoints.py`: the `LedgerStale` comparison function and the env
  flag. Not wired to any decision yet.
- Test: `tests/test_checkpoint_ledger.py` — for each mutator family
  (points, colour, uniforms, tracker value, submobject add/remove,
  updater add/remove, z_index, target, lock, animating status) assert
  the revision changed; assert reading points, bounding boxes, joint
  angles and unit normals does **not** change it (the derived-column
  rule); assert a child change bumps the parent and grandparent.

No behaviour changes in this phase; it can land alone.

*Landed 2026-09-05.* `Mobject.revision` bumps in `note_changed_data`,
`note_changed_family`, and a new `note_changed_state` (uniforms,
updaters, locks, targets, z_index, depth test, clip plane, joint type,
tracker values, camera orientation, glow). `_is_animating` is treated
as render-only: it flips at play begin and end and is excluded from the
verify comparison rather than bumped. `ledger_stale_attribute` and
`LedgerStale` live in `scene/checkpoints.py`; `MANIML_VERIFY_LEDGER=1`
is read by `verify_ledger_enabled()` and is not yet wired to a decision.
Tests: `tests/test_checkpoint_ledger.py`.

### Phase 2 — The ledger (two to three days)

- `deepcopy_namespace` gains an optional `ledger` argument and a
  `direction` (`"freeze"` for live→checkpoint, `"thaw"` for
  checkpoint→live). `_save_checkpoint` and `_create_checkpoint_zero`
  pass `"freeze"`; `_restore_checkpoint_for_display`,
  `_replay` / execution copy, and `SceneState.copy` pass `"thaw"`.
- Freeze direction: collect the live mobject set (families of
  `SceneState.mobjects` plus Mobject values and Mobject-bearing
  containers in `must_copy`); pre-seed the memo from reusable ledger
  entries; deep-copy; for every *new* frozen mobject strip `parents`,
  freeze arrays, compute the leaf flag, record the ledger entry;
  update the counters.
- Thaw direction: deep-copy; relink parents from the submobject side;
  seed the ledger from the memo.
- The `_rebind_functions` guard.
- Tests, all headless through the `CheckpointSceneTest` harness:
  - an untouched square is the *same object* in consecutive checkpoints;
    a moved one is not, and the earlier checkpoint's copy still holds
    the earlier position;
  - each structural change in Phase 1's list produces a fresh copy;
  - a mobject with an updater, a target, or a saved state is copied
    every time;
  - after a restore, every child's `parents` is exactly its parent in
    the restored graph, and moving the child updates the parent's
    bounding box;
  - writing into a checkpoint's mobject raises;
  - the play after a step back reuses the untouched mobjects;
  - the ledger holds one entry per live mobject after many static
    plays (memory bound);
  - the whole existing `test_checkpoint_reload.py`, including the
    ghost regression, passes unchanged.
- Run the full suite with `MANIML_VERIFY_LEDGER=1` and fix every
  `LedgerStale` by adding the missing bump. The suite is not green for
  this phase until verify mode is silent.

Exit: `checkpoint.save_copy` under 2 ms on a static play in the Phase 0
scene; typical plays cost the moved mobjects only; counters show reuse.

*Landed 2026-09-05.* `deepcopy_namespace(..., ledger=, mode=)`;
`Mobject.__deepcopy__` reads a copy mode (`copy_mode()` in
`mobject.py`): "freeze" drops parent links and marks the arrays
read-only, "thaw" rebuilds parent links from the submobject side, None
is a plain deep copy (what `SceneState.copy()` for undo still uses).
`CheckpointLedger` lives on the scene as `checkpoint_ledger`. The two
places that used to put a stored checkpoint's state on screen directly
(the edit re-anchor and the exec-error rollback) go through
`thaw_state` now. `insert_submobject` sets the child's parent link,
which it never did. Tests: the `LedgerReuse` and
`VerifyModeCatchesABypass` cases in `tests/test_checkpoint_ledger.py`.

### Phase 2b — Reuse on thaw (one to two days)

The baseline showed the other half of the stall: `run_next_animation`
deep-copies the stored checkpoint before every exec
(`checkpoint.execution_copy`, 188 ms p50 on EpisodeA3, the same as the
save), and every display restore does the same (`restore_copy`). The
ledger fixes the save; the thaw needs the trick reversed. When thawing
checkpoint *C*, a live mobject whose ledger entry's frozen copy is the
very object in *C* and whose revision still matches is already the
right state: pre-seed the thaw memo `frozen -> live` for those and only
the changed ones are copied. For a RIGHT press this is nearly
everything, since the live scene *is* the checkpoint being thawed
except for what the last play moved. The live objects keep their
parents; relink only the fresh copies. Same tests as Phase 2 from the
other direction, plus: after thaw, the live namespace variable and the
on-screen object are still the same object, and an edit-replay from an
earlier checkpoint still produces fresh copies (its live objects do
not match that checkpoint's frozen ones).

Exit: `checkpoint.execution_copy` and `restore_copy` under 2 ms when
stepping forward through a static stretch.

*Landed 2026-09-05, the forward half.* After a unit finishes, the live
scene and `_live_namespace` are exactly what the last save froze from,
so `run_next_animation` runs the next unit against them and skips the
thaw entirely (`_live_is_checkpoint`; `Scene.restore_state` and a
rebuilt checkpoint zero clear it). That is the case the other session's
measurement called "skip the execution copy at the frontier", and it
removes the thaw from every RIGHT press. The reverse — a step back
still thaws the whole checkpoint — is the remaining part of this
phase.

### Phase 3 — Dogfood under verify, then decide (during course work)

*First run, 2026-09-05:* `EpisodeA3 --render` under
`MANIML_VERIFY_LEDGER=1` raised once, at unit 87: `Table` changed in
`mob_table`. The table's entries live in `mob_table`, a list of lists,
and the reference walk only looked one container level deep, so an
entry that changed after leaving the table's family did not spoil the
table's reuse. The walk follows nested containers now (four levels),
and the render runs clean. That is the mode working as designed: a
miss became a named exception at the next save instead of a stale
checkpoint.

Run the course episodes and the dogfood scenes with verify mode on
for a week of real use. Every `LedgerStale` is a missed bump with its
attribute named. When a week passes clean, leave verify off by default,
record the before/after numbers here and in `DECISIONS.md`, and update
TODO.md item 1.

### Phase 4 — Optional hardening: freeze the live arrays

Only if Phase 3 finds bypassing writes that verify mode catches too
late (at the next checkpoint rather than at the write). Freeze
`mobject.data` and array uniforms on live mobjects; sanctioned
mutators unfreeze, bump, refreeze. Three things the earlier notes did
not account for, all verified in this venv:

- **Pre-existing views stay writeable.** A view taken before the base
  is frozen, or inside an unfreeze window, keeps writing through. The
  freeze catches new views, not retained ones; `get_points()` should
  hand back a read-only view so user code that stashes one still
  fails loudly.
- **Derived columns live inside `data`.** The eight lazy writes to
  `joint_angle`, `base_normal` and `d_normal_point` happen during
  rendering and must go through a no-bump unfreeze helper, or the
  render pass raises on every frozen mobject.
- **Compatibility.** User code writing into `get_points()` starts
  failing and needs an error that names `set_points` /
  `apply_points_function`. That is the cost to weigh; verify mode
  gives most of the safety without it, which is why this is Phase 4
  and behind `MANIML_FREEZE_DATA=1` first.

### Later, not now

- **Widen the reuse rule.** Record the external references of each
  entry (updater closure cells and defaults, `target`, `saved_state`,
  Mobject-valued attributes) as `(weakref, revision)` pairs and make
  reusable mean "revision unchanged and every reference reusable".
  Worth it only if the counters show updater-bearing mobjects are a
  large share of the copied set.
- **Copy less.** Excluding `shader_wrapper`, triangulation caches and
  bounding-box caches from the frozen copy lowers the per-object
  constant for the mobjects that *are* copied. Small; do it when
  touching `Mobject.copy`.

## Risks and guards

| Risk | Guard |
| --- | --- |
| A mutation path misses the revision bump and a checkpoint goes stale silently | Verify mode compares every reuse and raises with the attribute; the suite and a week of course work run with it on before it is trusted |
| A reused entry references a changed mobject | Leaf-only reuse rule; `_rebind_functions` skips pre-seeded ids |
| Stale `parents` through shared copies | Frozen graphs carry no parent links; thaw relinks from the submobject side; test asserts it |
| History mutated through a live reference | Frozen arrays are read-only; the ghost test and a write-raises test cover it |
| Ledger keyed by a recycled `id()` | `WeakKeyDictionary` keyed by the object, never by `id` |
| Derived columns look like changes | They never pass a choke point, so the revision ignores them; verify mode excludes them from the comparison |
| Edit re-execution or `_rebind_functions` regresses | The whole `test_checkpoint_reload.py` runs unchanged; `deepcopy_namespace` keeps its single-memo structure |

## Out of scope, on purpose

Copy-on-write, write interception on live objects (beyond Phase 4's
optional freeze), deferring copies to idle time ("copy later" —
unnecessary once a static play costs nothing), and anything from the
instruction-stream architecture. The ledger removes the stall on this
engine and the revision counter is the first thing that architecture
needs anyway.
