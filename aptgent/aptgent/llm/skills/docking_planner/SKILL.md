---
id: docking_planner
name: Docking Planner
description: Suggest docking parameters (top_k / grid size / exhaustiveness) with explanatory notes. Numeric suggestions are clamped by the workflow validator; the skill also produces free-text rationale and confirmation notes.
when_to_use: During the docking selection step, after `compute_deterministic_docking_plan()` has produced the baseline numeric recommendation and the workflow wants the LLM to refine it with domain insight.
version: 2.0.0
trust_level: advisory
tags: [docking, planning, advisory]
inputs: [candidate_count, machine_profile, time_budget_hours, computed_top_k, computed_time_budget_hours, computed_grid_size, target_smiles, target_name]
outputs: [recommended_top_k, recommended_grid_size, recommended_exhaustiveness, receptor_path_note, grid_center_note, reason]
---

# Docking Planner Skill

The LLM receives a deterministic docking draft plus target molecule info
(SMILES and name when available). It may suggest refined numeric values for
`top_k`, `grid_size`, and `exhaustiveness`, constrained to the bounds enforced
by `validate_docking_recommendation_result()`. The workflow's validator clamps
any out-of-range suggestion back to the deterministic defaults, so the skill
is safe even when the LLM produces unexpected values.

The skill also writes a `reason` paragraph and two manual-confirmation notes
(`receptor_path_note`, `grid_center_note`) for the UI.
