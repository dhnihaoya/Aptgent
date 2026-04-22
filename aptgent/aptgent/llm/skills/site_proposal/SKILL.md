---
id: site_proposal
name: Site Proposal
description: Suggest which aptamer positions are tolerable mutation sites, given sequence + secondary structure + user notes.
when_to_use: After the secondary structure step, when the workflow wants LLM-suggested candidate mutation positions (used as hints, not final state).
version: 1.0.0
trust_level: advisory
tags: [sites, mutation, advisory]
inputs: [sequence, secondary_structure, user_notes]
outputs: [proposals, proposed_sites, reasoning, confidence]
---

# Site Proposal Skill

Proposes 3 alternative plans of 0-based mutation-site indices that are
likely to tolerate changes without destroying the fold. The plans are ordered
as conservative, aggressive, and one additional LLM-selected direction. The
aggressive plan should include the conservative plan's sites when structurally
reasonable. The skill is advisory and never decides the final confirmed sites
-- that decision still belongs to the user through the Site Proposal UI. The
first proposal is the preferred plan and is mirrored in the legacy
`proposed_sites`, `reasoning`, and `confidence` fields for compatibility.

In addition to the structured JSON API (`invoke` / `invoke_stream`), the
skill also supports a `rephrase` mode that converts a free-form user
instruction (e.g. "mutate the loop region") into an explicit list of
indices. That mode uses a smaller, dedicated system prompt located at
`system_rephrase.md`.
