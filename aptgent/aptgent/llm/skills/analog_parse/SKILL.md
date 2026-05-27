---
id: analog_parse
name: Analog Name Parser
description: Extract molecule names from natural language text for specificity screening.
when_to_use: When the user describes desired analogs in natural language during the specificity filter step.
version: 1.0.0
trust_level: advisory
tags: [specificity, analogs, nlu]
inputs: [text]
outputs: [molecule_names]
---

# Analog Name Parser Skill

Given a user's natural language description of desired analog molecules,
extract the molecule names. Handles casual language, hedging, and implicit
references.
