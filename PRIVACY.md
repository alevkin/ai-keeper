# Privacy

AI Keeper is designed for local token accounting without copying chat content.

## What AI Keeper Stores

AI Keeper stores metadata such as:

- token counts
- timestamps
- provider and model labels
- cwd and git metadata
- session ids
- transcript paths
- transcript offsets and ingest watermarks
- aggregate cost estimates

## What AI Keeper Does Not Store

AI Keeper does not store prompts, assistant messages, raw transcript contents,
or copied chat JSON in its own database. It may keep paths and offsets pointing
to local provider files so it can resume metadata ingestion without duplicating
the source content.

## Local-Only Default

AI Keeper is local-only by default. It runs on the local machine and stores its
SQLite database under `$AIKEEPER_HOME`, defaulting to `~/.aikeeper`. There is no
remote sync or multi-user service in the current release.

## Audits

Use these checks before sharing diagnostics or publishing a release:

```bash
uv run aikeeper audit privacy --json
uv run aikeeper audit distribution --json
```

Diagnostics bundles are expected to contain metadata, health checks, and bounded
logs. They should not include prompts, assistant messages, raw transcripts, or
the SQLite database file.
