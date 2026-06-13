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

Open <http://127.0.0.1:8765> for the dashboard. If that port is busy, run the
daemon with `--port 8766`.

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
creates a `.bak` copy first. The hooks emit a short summary after each turn:

```text
AI Keeper | turn X tokens ($A est.) | session Y tokens ($B est.) | task today Z tokens | project today W tokens | dashboard
```

## Cost Estimates

AI Keeper estimates USD spend locally from stored token events and the bundled
OpenAI API pricing catalog. Estimates use Standard token prices from the
official OpenAI pricing page, retrieved on 2026-06-13, and are labeled as
estimates in the UI.

The official OpenAI Admin Costs API reports real organization-level billing
costs, but it requires an admin key and does not automatically map costs to
AI Keeper's local Codex project/task/session attribution.

## Dashboard Metrics

The overview dashboard includes:

- Active burn rate for the current session, shown as tokens/min and USD/min.
- Model efficiency by provider/model, including total tokens, total estimated
  spend, active speed, spend rate, and cached input ratio.
- Project, task, session, and turn token totals.

Burn-rate windows exclude long idle gaps, so the rate is about active agent work
rather than the total time a session stayed open.

## Budget Guards

Budget guards are soft warnings. They never block Codex. Configure them in
`$AIKEEPER_HOME/budgets.toml` or set `AIKEEPER_BUDGETS_FILE` to another TOML
file.

```toml
[defaults]
warn_at = 0.8
project_daily_usd = 25
task_daily_usd = 10
session_usd = 5
turn_usd = 1
project_daily_tokens = 1000000
task_daily_tokens = 500000
session_tokens = 750000
turn_tokens = 100000

[tasks.AIK-42]
task_daily_tokens = 300000
task_daily_usd = 20
```

Warnings appear in the dashboard and in the Codex hook summary when usage
crosses `warn_at * limit`.

## Analysis Features

AI Keeper also tracks:

- Context health on session pages, including cache ratio, input growth, and
  compaction guidance.
- Anomalies such as large turns, cost jumps, cache regressions, and project model
  switches.
- Savings simulations that reprice stored token events against another model.
- Metadata-only exports in Markdown, CSV, and JSON.

## OpenAI Costs Import

Estimated local spend is still the primary project/task/session attribution
source. You can additionally import official organization-level OpenAI Admin
Costs API buckets when you have an admin key:

```bash
OPENAI_ADMIN_KEY=... uv run aikeeper sync openai-costs --start-time 1730419200
```

Imported costs are aggregate billing buckets. They are stored separately from
local Codex attribution because the OpenAI Costs API does not automatically map
organization spend to local AI Keeper tasks.

## Claude Adapter

Claude support imports local JSONL metadata from `$CLAUDE_HOME/projects`,
defaulting to `~/.claude/projects`.

```bash
uv run aikeeper sync claude
```

Like Codex ingestion, Claude ingestion stores token counts, timestamps, model,
cwd, session id, transcript path, and offsets only.

## CLI

```bash
uv run aikeeper status --cwd "$PWD" --json
uv run aikeeper sync codex --once
uv run aikeeper sync claude
uv run aikeeper simulate --target-model gpt-5.4-mini
uv run aikeeper export --format markdown
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
