# Documents

The living records are at the repository root: `CLAUDE.md` (the
architecture as it stands), `TODO.md` (the roadmap) and `DECISIONS.md` (what
was decided, shipped or dropped, with reasoning). Everything here is a plan,
a review record, a measurement record or a field report, and each one has a
status. When a document is superseded it stays for its evidence; it is not a
source of current numbers or current direction.

## Current

| Document | What it is |
| --- | --- |
| [unified_triangle_renderer_phase_a.md](unified_triangle_renderer_phase_a.md) | The Phase A contract: shared native and browser output, AA, stencil ownership, resource retention, limits and validation. |
| [phase_b_plan.md](phase_b_plan.md) | Phase B as decided on 2026-09-11: everything is Bézier control points, evaluated on the GPU at screen density; increments B1 fills, B2 surfaces as nets, B3 animations as programs. B1 is in its prototype week. |
| [phase_b1_plan.md](phase_b1_plan.md) | B1's design (fan and patch triangles counted on the stencil, decided by Taylor 2026-09-11), the mechanism probe, the prototype week, and its measured results as they land. |
| [text_parity_plan.md](text_parity_plan.md) | The plan for closing the zoom-step gap between Phase A and Original 2D on text, with the measured breakdown. Executed 2026-09-10 (DECISIONS.md, "A zoom step rebuilds nothing the camera did not change"); kept for the breakdown. |
| [gpu_geometry_generation_plan.md](gpu_geometry_generation_plan.md) | The Phase B specification: GPU source evaluation and correct geometry generation. Not started. |
| [unified_triangle_renderer_review_response.md](unified_triangle_renderer_review_response.md) | The implementer's dispositions of every review round, with measurements. Append here; do not edit the reviewer's files. |
| [unified_triangle_renderer_code_review.md](unified_triangle_renderer_code_review.md) | The reviewer's rounds. Reviewer-owned: implementers respond in the response document. |
| [read_instrumentation_2026-09-11.md](read_instrumentation_2026-09-11.md) | Point reads by kind (raw, reduce) and phase (play, updater, idle) on EpisodeB0, A2, A3: the Phase B sync-policy prerequisite, with the sites that dominate and the author's reading. |
| [ce_compat_notes.md](ce_compat_notes.md) | Field report from the ECON 0100 episode ports: every CE divergence that bit. Open items live in `TODO.md`. |
| [dogfood_2026-09-09.md](dogfood_2026-09-09.md) | Field report from EpisodeB0 dogfood. Its diagnoses were acted on 2026-09-10 (`DECISIONS.md`, "The 2026-09-09 dogfood report"); its numbers are historical. |

## Superseded, kept for evidence

| Document | Superseded by |
| --- | --- |
| [unified_triangle_renderer_plan.md](unified_triangle_renderer_plan.md) | The plan that selected one triangle renderer for 2D and 3D, with the reviewer's notes. Phase A shipped; the current contract is the Phase A record above, and Phase B has its own specification. |
| [unified_triangle_renderer_a0_results.md](unified_triangle_renderer_a0_results.md) | The A0 prototype experiments. Evidence for the plan, not measurements of the current renderer. |
| [unified_triangle_renderer_a1_integration.md](unified_triangle_renderer_a1_integration.md) | The former opt-in route. The default cutover replaced it. |
| [ordered_fill_atlas_plan.md](ordered_fill_atlas_plan.md) | The atlas proposal; the unified renderer plan superseded it. |
| [bounded_fill_plan.md](bounded_fill_plan.md), [helper_inlining_plan.md](helper_inlining_plan.md) | Winding-renderer plans; the winding path is now the viewer's Original 2D comparison only. |
| [checkpoint_ledger_plan.md](checkpoint_ledger_plan.md) | The ledger shipped 2026-09-05 (`DECISIONS.md`, "Checkpoints are a ledger"); reuse on thaw remains open in `TODO.md`. |
| [performance_2026-08.md](performance_2026-08.md) | The 2026-08 measurement record for the pixel stream and pyglet window, both deleted 2026-09-02. Only its AddTextWordByWord diagnosis is still referenced. |
| [handoff_claude_fable_20260910.md](handoff_claude_fable_20260910.md), [plan_for_claude_fable_20260910.md](plan_for_claude_fable_20260910.md) | The handoff and work plan for the 2026-09-10 session. Packages 1 through 4 and the roadmap reconciliation are done; read the response document and `DECISIONS.md` for what happened. Their setup checklist and measurement rules still apply. |
