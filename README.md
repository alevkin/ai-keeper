# AI Keeper

Local-only token usage daemon and dashboard for Codex.

AI Keeper stores metadata only: token counts, model, cwd, git metadata, session ids,
transcript paths and ingest offsets. It does not copy prompts, assistant messages,
or raw transcript JSON into its own database.

## Stack

- Python 3.13
- FastAPI + Uvicorn
- Typer + Rich CLI
- SQLite storage at `$AIKEEPER_HOME/aikeeper.sqlite`
- Server-rendered Jinja pages with a small CSS layer

## Quick Start

```bash
uv run aikeeper sync codex --once
uv run aikeeper daemon start
```

Open <http://127.0.0.1:8765> for the dashboard.

## Codex Hooks

Install hooks globally:

```bash
uv run aikeeper install codex-hooks --scope user
```

Or install them for only the current project:

```bash
uv run aikeeper install codex-hooks --scope project
```

The installer writes or merges a `hooks.json` with `SessionStart`,
`UserPromptSubmit`, and `Stop` handlers. If a hooks file already exists, AI Keeper
creates a `.bak` copy first. The `Stop` hook emits a short summary after each turn:

```text
AI Keeper: turn X tokens; session Y; task today Z; project today W.
```

## CLI

```bash
uv run aikeeper status --cwd "$PWD" --json
uv run aikeeper sync codex --once
uv run aikeeper codex exec -- "summarize this repository"
```

`aikeeper codex exec -- ...` wraps `codex exec --json`, streams Codex output
unchanged, and records `turn.completed.usage` as local token events.

## Codex Data Sources

AI Keeper reads:

- `$CODEX_HOME/state_5.sqlite`, defaulting to `~/.codex/state_5.sqlite`
- `$CODEX_HOME/sessions/**/*.jsonl`
- `$CODEX_HOME/archived_sessions/*.jsonl`
- `codex exec --json` streams when using the wrapper

## Task Attribution

Project attribution uses the git root when available, otherwise `cwd`.
Task attribution uses a git branch issue id such as `AIK-42`, then the branch
name, then `unassigned`.

## Development

```bash
uv run pytest -q
```
