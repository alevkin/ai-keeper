# AI Keeper

[![CI](https://github.com/alevkin/ai-keeper/actions/workflows/ci.yml/badge.svg)](https://github.com/alevkin/ai-keeper/actions/workflows/ci.yml)
[![Privacy](https://img.shields.io/badge/privacy-metadata--only-2f6f5e)](PRIVACY.md)
[![Local only](https://img.shields.io/badge/runtime-local--only-334155)](README.md)

Turn AI agents from an open-ended burn rate into a managed engineering budget.

AI Keeper is a local Task Economics dashboard for Codex and Claude usage. It
shows what each AI-assisted implementation task costs, how fast the current
task is spending, and when the next prompt should get smaller.

It is built for developers who care about AI implementation cost per useful outcome,
not just raw token totals.

Product page: [andrei.levk.in/ai-keeper](https://andrei.levk.in/ai-keeper/)
User guide: [docs/user-guide.md](docs/user-guide.md)

## Why AI Keeper

AI coding tools are becoming part of daily engineering work, but the cost of a
single useful outcome often stays invisible until a bill, a quota, or a slow
session surprises you.

AI Keeper makes task economics visible while keeping the sensitive parts local:

- See what the current task has cost so far and what the next 30 active minutes
  are likely to add.
- Compare the current task with your learned baseline for similar work.
- Review the Task Ledger by phase, provider, model, turn, tokens, and estimated
  cost.
- Get a small next-best-move hint when the task starts drifting.
- Estimate cost from local token events and bundled pricing data.
- Spot active burn rate, cache behavior, large turns, and model switches.
- Keep prompts, assistant messages, and raw transcripts out of AI Keeper's
  database.

## What You Get

- **Efficiency dashboard**: Task Economics, live rate, cost drivers, Task Ledger,
  provider mix, budgets, and health.
- **Task Economics**: spent so far, projected next 30 minutes, learned baseline,
  and current status for the active task.
- **Next best move**: lightweight guidance to narrow prompts, split work, or
  commit useful slices before agent work drifts.
- **Codex hook summary**: after each turn, see current turn, session, task, and
  project totals with a dashboard link.
- **Claude metadata import**: sync local Claude JSONL usage, including cache
  read and cache write tokens, without storing message content.
- **Cost estimates**: local USD estimates for stored token events.
- **Active rate**: tokens/min and estimated USD/min during active agent work.
- **Budgets**: soft warnings by project/task/session without blocking Codex.
- **Health checks**: ingest health, missing source details, diagnostics bundles,
  and service status.
- **Privacy audit**: checks that stored data remains metadata-only.
- **Portable shape**: provider-neutral storage with Codex and Claude adapters.

## Install

Homebrew tap:

```bash
brew install alevkin/tap/aikeeper
```

The Homebrew formula runs the local installer after download. It starts the
user LaunchAgent, installs Codex hooks, and prepares the dashboard on port
`8766`.

If you need to repair the local setup later:

```bash
aikeeper-install --port 8766
```

From a checkout:

```bash
uv run aikeeper install all --port 8766
uv run aikeeper doctor --port 8766
```

Open the dashboard:

```text
http://127.0.0.1:8766
```

Install or refresh local developer git hooks:

```bash
scripts/install-git-hooks.sh
```

## How It Feels

After Codex hooks are installed, each turn can include a short usage line:

```text
AI Keeper | turn 85,673 tokens ($0.07 est.) | session 14,195,171 tokens ($12.40 est.) | task today 5,697,011 tokens | project today 5,697,011 tokens | dashboard
```

The dashboard gives the bigger picture: Task Economics, active burn rate, cost
drivers, task ledger, provider mix, budgets, model efficiency, and ingest
health.

## Privacy Model

AI Keeper is local-only and metadata-only by default.

It stores:

- token counts
- timestamps
- model labels
- cwd and git metadata
- session ids
- transcript paths and ingest offsets
- pricing and budget metadata

It does not store:

- prompts
- assistant messages
- raw transcript JSONL
- copied chat content

Run a privacy check:

```bash
uv run aikeeper audit privacy --json
```

Private company, project, path, and author markers are configured outside the
repository in `$AIKEEPER_HOME/private-markers.toml` or the path pointed to by
`AIKEEPER_PRIVATE_MARKERS`. See [Private Markers](docs/private-markers.md).

## Commands You Will Actually Use

```bash
uv run aikeeper doctor --port 8766
uv run aikeeper service status --port 8766
uv run aikeeper sync codex --once
uv run aikeeper sync claude --once
uv run aikeeper audit distribution --json
uv run aikeeper diagnostics bundle --port 8766
uv run aikeeper export --format markdown
```

Service controls:

```bash
uv run aikeeper service start
uv run aikeeper service stop
uv run aikeeper service restart
uv run aikeeper service uninstall
```

## Data Sources

Codex support reads local metadata from:

- `$CODEX_HOME/state_5.sqlite`
- `$CODEX_HOME/sessions/**/*.jsonl`
- `$CODEX_HOME/archived_sessions/*.jsonl`
- `codex exec --json` streams when using the wrapper

Claude support reads local metadata from:

- `$CLAUDE_HOME/projects/**/*.jsonl`

Claude sync is explicit:

```bash
uv run aikeeper sync claude --once
```

## Release And Distribution

Build release artifacts locally:

```bash
scripts/package.sh --version v0.25.2 --output-dir dist
scripts/sign-release.sh --dist-dir dist --signer none
```

Run the public release gate before changing repository visibility:

```bash
scripts/public-release-gate.sh --version v0.25.2 --output-dir dist --online
```

Release artifacts are signed in GitHub Actions with keyless `cosign`. See
[Release Verification](docs/release-verification.md).

## Development

```bash
uv run pytest -q
```

Useful docs:

- [Privacy](PRIVACY.md)
- [Contributing](CONTRIBUTING.md)
- [Public Release Checklist](docs/public-release-checklist.md)
- [Public Release Gate](docs/public-release-gate.md)
- [GitHub Ops Status](docs/github-ops-status.md)
