---
name: ai-keeper
description: Inspect local Codex token usage captured by AI Keeper without reading raw chat transcripts.
---

# AI Keeper

Use this skill when a user asks about Codex token usage, project/task/session
token totals, or whether AI Keeper is collecting usage.

## Rules

- Prefer AI Keeper metadata commands over reading raw Codex transcript content.
- Do not open or summarize prompts, assistant messages, or full rollout JSONL unless the user explicitly asks for transcript inspection.
- Use `aikeeper status --cwd "$PWD" --json` for the current workspace.
- Use `aikeeper sync codex --once` before reporting totals if freshness matters.
- Mention that costs are not estimated in the MVP; AI Keeper tracks tokens only.

## Useful Commands

```bash
aikeeper status --cwd "$PWD" --json
aikeeper sync codex --once
aikeeper daemon start
aikeeper install codex-hooks --scope user
```
