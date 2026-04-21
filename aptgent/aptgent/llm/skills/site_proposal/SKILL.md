---
id: site_proposal
name: Site Proposal
description: Suggest which aptamer positions are tolerable mutation sites, given sequence + secondary structure + user notes.
when_to_use: After the secondary structure step, when the workflow wants LLM-suggested candidate mutation positions (used as hints, not final state).
version: 1.0.0
trust_level: advisory
tags: [sites, mutation, advisory]
inputs: [sequence, secondary_structure, user_notes]
outputs: [proposed_sites, reasoning, confidence]
---

# Site Proposal Skill

Proposes 0-based mutation-site indices that are likely to tolerate changes
without destroying the fold. The skill is advisory and never decides the
final confirmed sites — that decision still belongs to the user through
the Site Proposal UI.

In addition to the structured JSON API (`invoke` / `invoke_stream`), the
skill also supports a `rephrase` mode that converts a free-form user
instruction (e.g. "mutate the loop region") into an explicit list of
indices. That mode uses a smaller, dedicated system prompt located at
`system_rephrase.md`.
