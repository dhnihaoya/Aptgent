---
id: docking_planner
name: Docking Planner
description: Suggest docking parameters (top_k / exhaustiveness) with explanatory notes. Numeric suggestions are clamped by the workflow validator; the skill also produces free-text rationale and confirmation notes.
when_to_use: During the docking selection step, after `compute_deterministic_docking_plan()` has produced the baseline numeric recommendation and the workflow wants the LLM to refine it with domain insight.
version: 3.0.0
trust_level: advisory
tags: [docking, planning, advisory]
inputs: [candidate_count, machine_profile, time_budget_hours, computed_top_k, computed_time_budget_hours, target_smiles, target_name]
outputs: [recommended_top_k, recommended_exhaustiveness, receptor_path_note, grid_center_note, reason]
---

# Docking Planner Skill

The LLM receives a deterministic docking draft plus target molecule info
(SMILES and name when available). It may suggest refined numeric values for
`top_k` and `exhaustiveness`, constrained to the bounds enforced by
`validate_docking_recommendation_result()`. The workflow's validator clamps
any out-of-range suggestion back to the deterministic defaults, so the skill
is safe even when the LLM produces unexpected values.

The grid box is no longer LLM-driven: it is computed deterministically to
cover the entire aptamer per Aptamers-2026.5.4.docx §2.4.4. The skill still
writes a `reason` paragraph and two manual-confirmation notes
(`receptor_path_note`, `grid_center_note`) for the UI.
