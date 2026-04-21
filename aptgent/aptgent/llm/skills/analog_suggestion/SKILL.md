---
id: analog_suggestion
name: Analog Suggestion
description: Propose 2-4 structurally similar small molecules for specificity screening against a target.
when_to_use: During the specificity filter step, when the user wants LLM-suggested analog controls to complement (but not replace) the deterministic analog list.
version: 1.0.0
trust_level: advisory
tags: [specificity, analogs, chemoinformatics]
inputs: [target_name, smiles]
outputs: [analogs, note]
---

# Analog Suggestion Skill

Given a target small molecule (name and optional SMILES), suggest a small
number of close structural analogs that can serve as specificity controls.
The skill is advisory: the workflow still runs any deterministic analogs
the user supplied during intake.
