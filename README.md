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

Install everything needed for the local MVP: SQLite schema, Codex hooks, and the
macOS LaunchAgent daemon.

```bash
uv run aikeeper install all --port 8766
uv run aikeeper doctor --port 8766
```

Or use the lightweight install script:

```bash
scripts/install.sh --port 8766
```

Open <http://127.0.0.1:8766> for the dashboard. After the hooks are installed,
Codex turn summaries include a dashboard link when the daemon is reachable.
Use <http://127.0.0.1:8766/system> for local service status, paths, logs, and
recovery commands. The System page can queue confirmed background actions for
repair, reinstall, restart, and metadata-only diagnostics, then track them as
observable jobs with queued, running, ok, or fail status.
Use <http://127.0.0.1:8766/diagnostics> to create metadata-only diagnostics
bundles, download recent archives, and inspect recent system jobs.

For manual one-off use:

```bash
uv run aikeeper sync codex --once
uv run aikeeper daemon start
```

Open <http://127.0.0.1:8765> for the dashboard. If that port is busy, run the
daemon with `--port 8766`.

## macOS Service

For a persistent dashboard, install AI Keeper as a user LaunchAgent. `launchd`
starts it at login and restarts it if the daemon exits.

```bash
uv run aikeeper service install --port 8766
uv run aikeeper service status --port 8766
```

Useful service commands:

```bash
uv run aikeeper service start
uv run aikeeper service stop
uv run aikeeper service restart
uv run aikeeper service uninstall
uv run aikeeper service status --port 8766 --json
```

`doctor --fix` repairs the common local install drift: missing app home,
uninitialized SQLite database, missing Codex hooks, and a missing or stopped
LaunchAgent.

```bash
uv run aikeeper doctor --fix --port 8766
```

Use `uv run aikeeper uninstall all` to remove the LaunchAgent and AI Keeper
Codex hook entries together. It keeps the local SQLite database by default.

Upgrade and rollback helpers:

```bash
scripts/upgrade.sh --port 8766 --target v0.15.0
scripts/rollback.sh --port 8766 --target v0.12.0
```

The installer writes `~/Library/LaunchAgents/com.aikeeper.daemon.plist` when
that directory is writable. If it is not writable, AI Keeper falls back to
`$AIKEEPER_HOME/LaunchAgents/com.aikeeper.daemon.plist` and bootstraps that file
with `launchctl`. Daemon logs go to `$AIKEEPER_HOME/logs/daemon.stdout.log` and
`$AIKEEPER_HOME/logs/daemon.stderr.log`.

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

Budget guards are soft warnings. They never block Codex. Configure them in the
dashboard; AI Keeper stores budget settings in the local SQLite database.

The overview page supports default budgets and an override for the current task.
The API exposes the stored configuration at `/api/budgets`.

Warnings appear in the dashboard and in the Codex hook summary when usage
crosses `warn_at * limit`.

`budgets.toml` is still supported as an explicit legacy override for commands
that accept `--budget-path`, but it is no longer the default configuration path.

## Analysis Features

AI Keeper also tracks:

- Privacy audits that check the local database schema and sampled text columns
  for prompt, assistant, or raw transcript storage.
- Ingest health for sessions, token events, transcript paths, ingest offsets,
  lagging sources, and unpriced model labels.
- Ingest health details for missing transcript paths and source offset lag,
  shown without transcript contents.
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
uv run aikeeper audit privacy --json
uv run aikeeper health ingest --json
uv run aikeeper diagnostics bundle --port 8766
uv run aikeeper jobs run --job-id 1 --json
uv run aikeeper simulate --target-model gpt-5.4-mini
uv run aikeeper export --format markdown
uv run aikeeper codex exec -- "summarize this repository"
```

Diagnostics bundles are written under `$AIKEEPER_HOME/diagnostics` by default.
They contain doctor/system status, privacy/ingest health, service metadata, and
tail logs. They do not include prompts, assistant messages, raw transcripts, or
the SQLite database file.
The dashboard Diagnostics page can create these bundles directly and download
recent archives without exposing raw chat content.

System actions are stored as metadata-only jobs in SQLite. Each job records the
action name, command, cwd, status, timestamps, exit code, log path, and output
tail. It does not store prompts, assistant messages, or raw transcripts.

`aikeeper codex exec -- ...` wraps `codex exec --json`, streams Codex output
unchanged, and records `turn.completed.usage` as local token events.

## Packaging

`packaging/manifest.json` defines the current lightweight packaging contract:
local-only, metadata-only, script-driven install/upgrade/rollback. It is a base
for future macOS DMG, Homebrew, and Windows packaging rather than a full binary
installer today.

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
