# CLAUDE.md

This repository uses `AGENTS.md` as the canonical guide for AI coding agents.

Claude Code (and any other agent tool) should read [`AGENTS.md`](./AGENTS.md) for:

- current repository layout and entry points
- the real chat-first TUI path (`ChatScreen` + `tui/steps/*`)
- workflow step order (defined in `aptgent/aptgent/workflow/engine.py`)
- step handler dispatch (`tui/steps/factory.py` → per-step modules)
- adapter, workflow, LLM, jobs, and predictor-runtime boundaries
- LLM skill registry (6 skills in `llm/skills/`)
- detachable job system (`jobs/` + `tui/steps/job_mixin.py`)
- known configuration/environment risks and the minimal pre-change checklist

If this file and `AGENTS.md` disagree, trust `AGENTS.md` and the code; then
update both. Do not maintain two parallel descriptions of the project.

## 推送前检查

Before pushing to remote, always review and update CLAUDE.md and AGENTS.md to ensure they reflect the current codebase state (directory layout, entry points, workflow steps, new features, config changes).
