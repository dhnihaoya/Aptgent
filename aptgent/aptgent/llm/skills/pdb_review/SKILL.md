---
id: pdb_review
name: PDB Review
description: Semantic review of a PDB structure for aptamer workflow relevance. Classifies the structure into seven categories, checks whether the PDB ligand matches the user target, and produces a confidence level and factual note.
when_to_use: After the PDB analysis adapter has parsed a structure and the workflow needs to assess whether the PDB is aptamer-relevant and whether its ligand matches the user target.
version: 2.0.0
trust_level: advisory
tags: [pdb, review, classification, aptamer, ligand]
inputs: [title, hetnam_map, chains_sequences, ligand_display_names, user_target_text, user_target_smiles, user_sequence, summary]
outputs: [category, target_match, confidence, note]
---

# PDB Review Skill

Given a structured payload describing a PDB structure (title, chains, ligands,
HETNAM map, and optionally the user's target molecule), classify the structure
into one of seven categories, assess whether the PDB ligand matches the user
target, and produce a confidence level and factual note.

The skill is advisory — it never overrides what the PDB adapter already parsed.
When the classification indicates the structure is not aptamer-relevant
(or the target mismatches), the intake step may present a confirmation gate
to the user.
