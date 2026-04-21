# CLAUDE.md

This repository uses `AGENTS.md` as the canonical guide for AI coding agents.

Claude Code (and any other agent tool) should read [`AGENTS.md`](./AGENTS.md) for:

- current repository layout and entry points
- the real chat-first TUI path (`ChatScreen` + `tui/steps/*`)
- workflow step order (defined in `aptgent/aptgent/workflow/engine.py`)
- adapter, workflow, LLM, and predictor-runtime boundaries
- known configuration/environment risks and the minimal pre-change checklist

If this file and `AGENTS.md` disagree, trust `AGENTS.md` and the code; then
update both. Do not maintain two parallel descriptions of the project.
