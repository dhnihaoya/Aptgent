---
id: site_proposal
name: Site Proposal
description: Suggest which aptamer positions are tolerable mutation sites, given sequence + secondary structure + user notes.
when_to_use: After the secondary structure step, when the workflow wants LLM-suggested candidate mutation positions (used as hints, not final state).
version: 1.0.0
trust_level: advisory
tags: [sites, mutation, advisory]
inputs: [sequence, secondary_structure, user_notes]
outputs: [region_assessment, proposals, proposed_sites, reasoning, confidence]
---

# Site Proposal Skill

Produces a region-level risk assessment plus 3 alternative plans of 0-based
mutation-site indices. The assessment separates regions that look suitable for
safer scaffold mutation from suspected binding/core risk regions. The plans are
ordered as conservative, aggressive, and one additional LLM-selected direction.
The aggressive plan should include the conservative plan's sites when
structurally reasonable. The skill is advisory and never decides the final
confirmed sites -- that decision still belongs to the user through the Site
Proposal UI. The first proposal is the preferred plan and is mirrored in the
legacy `proposed_sites`, `reasoning`, and `confidence` fields for
compatibility.
