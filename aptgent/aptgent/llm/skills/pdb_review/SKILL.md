---
id: pdb_review
name: PDB Review
description: Semantic sanity check on a deterministic PDB summary. The skill classifies whether the structure looks aptamer-relevant; it does not reparse or re-fetch the PDB.
when_to_use: After the PDB analysis adapter has produced a text summary for a structure and the workflow wants a short, chat-friendly status label.
version: 1.0.0
trust_level: advisory
tags: [pdb, review, classification]
inputs: [summary]
outputs: [semantic_status, confidence, note]
---

# PDB Review Skill

Given a deterministic one-paragraph summary of a PDB structure (chains,
ligand candidates, sequence hints), classify it into one of three states
and produce a short factual note. The skill is advisory — it never
overrides what the PDB adapter already parsed.
