# AI Keeper User Guide

AI Keeper is a local-only usage dashboard for Codex and Claude. It helps you
answer where tokens and estimated cost go across projects, tasks, sessions, and
turns without copying prompts or assistant messages into its database.

## Install

Homebrew is the primary macOS install path:

```bash
brew install alevkin/tap/aikeeper
aikeeper-install --port 8766
```

Run setup after Homebrew finishes. That step:

- starts the local service on `127.0.0.1:8766`
- installs the Codex hooks
- creates the local SQLite database under `~/.aikeeper`
- runs a quick doctor check

Open the dashboard:

```text
http://127.0.0.1:8766
```

## Custom Port

To install on a different port:

```bash
aikeeper-install --port 8770
```

If AI Keeper is already installed, rerun the local installer:

```bash
aikeeper-install --port 8766
```

## Recovery

Use these when the service or hooks need a refresh:

```bash
aikeeper-install --port 8766
aikeeper-upgrade --port 8766
aikeeper-rollback --target v0.25.2 --port 8766
uv run aikeeper doctor --port 8766
```

## What It Stores

AI Keeper stores metadata that is useful for operations:

- token counts
- timestamps
- model labels
- cwd and git metadata
- session ids
- transcript paths and ingest offsets
- pricing and budget metadata

It does not store prompts, assistant messages, raw transcript JSONL, or copied
chat content.

## Daily Commands

```bash
uv run aikeeper service status --port 8766
uv run aikeeper sync codex --once
uv run aikeeper sync claude --once
uv run aikeeper diagnostics bundle --port 8766
uv run aikeeper audit privacy --json
uv run aikeeper audit distribution --json
```

## Workflow Harness

Workflow Harness makes useful outcomes easier to detect without storing prompt
or reply text. It uses project metadata: task branch names, conventional commit
subjects, local git hooks, explicit outcome markers, and verification signals.

Install local project guardrails:

```bash
aikeeper install workflow-harness --repo-root .
```

Record a verified useful slice:

```bash
aikeeper outcome done --status useful --type code
```

Inspect the current task's outcome coverage:

```bash
aikeeper outcome status --cwd . --json
aikeeper outcome suggest --cwd . --json
```

Recommended flow:

- use a feature branch with the task key in the name
- keep commits conventional, such as `feat: add workflow harness`
- run the relevant check before marking an outcome useful
- mark discarded or partial work so cost per useful outcome stays honest

## Codex Hooks

After hooks are installed, Codex turns can include a compact AI Keeper line with
turn cost, task cost, an efficiency signal, one next action, and a dashboard link. Hook output is metadata-only:
`UserPromptSubmit` explicitly discards prompt text, and `Stop` syncs token
events from local transcript metadata. The hook also adds a short Workflow
Harness reminder so agents keep work tied to a task and record verified
outcomes.

## Claude Metadata Sync

Claude support is an explicit local sync path:

```bash
uv run aikeeper sync claude --once
```

It reads usage metadata from `$CLAUDE_HOME/projects/**/*.jsonl`, including
input, cache read, cache write, and output token counts. AI Keeper stores the
session id, cwd, model, git branch, transcript path, ingest offset, timestamps,
and token counts only. It does not persist Claude message content or raw JSONL.
