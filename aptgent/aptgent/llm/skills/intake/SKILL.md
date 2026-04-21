---
id: intake
name: Intake
description: Parse a free-form user request into structured aptamer-design intake fields.
when_to_use: Run at the start of a workflow, whenever the user types a natural-language description of the desired aptamer and target.
version: 1.0.0
trust_level: nlu_only
tags: [intake, nlu, structured-extraction]
inputs: [user_text]
outputs: [initial_sequence, pdb_id, input_mode, target_molecule, modification_region, analogs, time_budget_hours, mixed_input_detected, missing_fields, follow_up_question]
---

# Intake Skill

Parses a single free-form user utterance into the structured intake payload
used by the aptamer design workflow. The skill is strictly NLU — it never
decides whether a candidate binds, what mutation to make, or how to rank
results. It only extracts what the user said.

Two modes are exposed:

* `invoke(user_text)` — JSON-mode extraction (system prompt: `system.md`).
* `explain_stream(user_text)` — plain-language summary for the chat UI
  (system prompt: `display.md`).

Downstream validation (`validate_intake_result`) is responsible for
normalising sequences and PDB IDs; the skill itself only guarantees the
JSON shape.
