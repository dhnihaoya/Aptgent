---
id: docking_planner
name: Docking Planner
description: Annotate a deterministic docking draft (top_k / time budget / grid size are fixed) with human-readable rationale and manual-confirmation notes.
when_to_use: During the docking selection step, after `compute_deterministic_docking_plan()` has produced the numeric recommendation and the workflow wants a short UI explanation.
version: 1.0.0
trust_level: deterministic_wrapper
tags: [docking, rationale, deterministic]
inputs: [candidate_count, machine_profile, time_budget_hours, computed_top_k, computed_time_budget_hours, computed_grid_size]
outputs: [receptor_path_note, grid_center_note, reason]
---

# Docking Planner Skill

Wraps a deterministic docking plan with an explanatory `reason` paragraph
and two manual-confirmation notes (`receptor_path_note`, `grid_center_note`).
The deterministic values are non-negotiable — the skill is explicitly
instructed not to change them, and the workflow's result validator
silently discards any numeric fields returned by the LLM, keeping the
computed values intact.

This is the only skill registered with `trust_level="deterministic_wrapper"`
to make the contract visible in any `/skills` introspection view.
