---
id: report
name: Report
description: Write the final report as Markdown from deterministic Aptgent workflow facts. Must never change ordering, scores, or labels.
when_to_use: Final report step, when the workflow wants an LLM-authored Markdown report on top of deterministic screening, docking, and ranking data.
version: 1.1.0
trust_level: advisory
tags: [report, summary, markdown]
inputs: [report_context]
outputs: [markdown_report]
---

# Report Skill

Takes deterministic workflow facts and writes a Markdown report for the TUI.
The report should detail only candidates that were selected for docking, because
those sequences are the ones intended for downstream documentation. Other
screened candidates should be summarized as aggregate counts, score ranges, and
filter outcomes rather than listed one by one.

The skill may explain and contextualize results, but it must never reorder,
rescore, relabel, or invent deterministic data.
