---
id: docking_params_parse
name: Docking Params NL Parser
description: Translate a user's natural-language sentence into partial AutoDock Vina docking-parameter overrides.
when_to_use: When the user types a free-text message in the docking selection step describing parameter intent (e.g. "试试 top 8, exhaustiveness 32, seed 42 / use LLM hint / skip docking").
version: 1.0.0
trust_level: nlu_only
tags: [docking, vina, nlu]
inputs: [text, current_params, candidate_count]
outputs: [top_k, exhaustiveness, num_modes, energy_range, grid_padding_angstrom, per_ligand_timeout_seconds, time_budget_hours, seed, action]
---

# Docking Params NL Parser Skill

The user is on the docking selection step and may describe Vina parameter
adjustments in plain language, possibly mixed with conversational hedging
("maybe try 32 exhaustiveness", "16 should be fine", "skip this step",
"use whatever the LLM suggests").

This skill turns that sentence into a partial JSON dict of overrides that
the workflow validator (`validate_docking_param_overrides`) can clamp and
apply to the strategy panel. **All numeric values are advisory only** —
they will be re-clamped by the deterministic validator before reaching
`state.docking_plan`.

Trust level is `nlu_only`: this skill never produces facts, only
interprets user intent.
