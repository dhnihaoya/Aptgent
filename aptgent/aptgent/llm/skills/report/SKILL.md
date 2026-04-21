---
id: report
name: Report
description: Write a short factual explanation of an already-ranked recommendation list. Must never change ordering, scores, or labels.
when_to_use: Final report step, when the workflow wants an LLM-authored summary on top of its deterministic ranking.
version: 1.0.0
trust_level: advisory
tags: [report, summary]
inputs: [recommendations]
outputs: [summary, candidate_notes]
---

# Report Skill

Takes a deterministically ranked list of recommendations and returns a short
summary paragraph plus per-candidate one-line notes keyed by `candidate_id`.
The system prompt explicitly forbids reordering, re-scoring, or relabeling
entries.
