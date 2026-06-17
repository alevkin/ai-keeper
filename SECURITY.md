# Security Policy

## Supported Versions

AI Keeper is pre-1.0 software. Security fixes are expected to ship on the
latest tagged release and the default branch.

## Reporting A Vulnerability

Use private disclosure for security issues while the repository is private.
Do not include prompts, assistant messages, raw transcripts, API keys, local
database files, or other sensitive local data in reports.

When possible, include:

- AI Keeper version and commit
- operating system and installation method
- affected command or page
- metadata-only reproduction steps
- relevant bounded logs with secrets removed

## Security Model

AI Keeper is local-only and metadata-only. It is designed to store token counts,
timestamps, model labels, paths, git metadata, session ids, and aggregate usage
fields. It should not store prompts, assistant responses, raw transcript JSON,
or copied chat content.

Before publishing or sharing a release, run:

```bash
uv run aikeeper audit privacy --json
uv run aikeeper audit distribution --json
```
