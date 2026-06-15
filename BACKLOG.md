# AI Keeper Backlog

AI Keeper stays local-only and metadata-only. Features below must keep prompts,
assistant messages, and raw transcript content out of the application database.

## Shipped

### AK-001 Live Burn Rate

Status: shipped in v0.4.0.

Show active spend velocity from recent token events.

- Display tokens/min and USD/min for current activity.
- Exclude long idle gaps so the rate reflects active agent work, not wall-clock
  waiting time.
- Provide a small recent-window trend for the dashboard.

Acceptance:

- `/api/overview` exposes a `burn_rate` object.
- Dashboard shows active tokens/min and USD/min.
- Tests cover idle-gap exclusion and unknown-model cost handling.

### AK-002 Model Efficiency

Status: shipped in v0.4.0.

Compare models by usage, speed, and spend efficiency.

- Show model, sessions, events, total tokens, total cost, average cost/turn,
  cached input ratio, tokens/min, and USD/min.
- Sort by total cost by default.
- Keep provider-neutral fields so Claude can be added later.

Acceptance:

- `/api/overview` exposes `model_efficiency` rows.
- Dashboard renders a model table.
- Tests cover multiple models and cached ratio.

### AK-003 Budget Guards

Status: shipped in v0.5.0.

Warn when a project, task, session, or turn approaches a configured token or USD
budget.

- Start with config-file budgets.
- Surface warnings in the dashboard and Codex hook summary.
- Keep enforcement soft in MVP: warn, do not block.

Acceptance:

- `/api/overview` exposes budget config state and warning rows.
- Dashboard renders configured budget warnings.
- Codex hook summary includes the top budget warning.
- Tests cover TOML config budgets, dashboard rendering, and hook output.

### AK-004 Task Budgets

Status: shipped in v0.6.0.

Attach budgets to branch/task keys.

- Derive defaults from branch issue IDs when available.
- Show budget burn-down and remaining estimate.
- Export task budget status.

Acceptance:

- Task-specific TOML overrides are supported under `[tasks.<task-key>]`.
- Project pages show task budget status.
- Exports include task budget status.

### AK-005 Context Bloat Tracker

Status: shipped in v0.6.0.

Track context growth and caching health.

- Show input/cached-input/output split over time.
- Highlight drops in cached input ratio.
- Suggest when a session is likely ready for compaction or restart.

Acceptance:

- Session pages show context health and compaction guidance.
- Service output exposes cache ratio and input growth.

### AK-006 Anomaly Detection

Status: shipped in v0.6.0.

Flag unusual turns.

- Detect large turns, sudden cost jumps, cache regressions, and model switches.
- Show anomalies on session and project pages.
- Include a concise reason for each anomaly.

Acceptance:

- Session pages flag large turns, cost jumps, and cache regressions.
- Project pages flag model switches.

### AK-007 Savings Simulator

Status: shipped in v0.6.0.

Estimate what a project/task/session would have cost on another model.

- Use the same token events with a selected target model price.
- Compare actual estimate vs simulated estimate.
- Keep tool/hosting costs out until they are modeled explicitly.

Acceptance:

- `/api/simulate` and `aikeeper simulate` reprice stored metadata.
- Overview dashboard shows common target-model scenarios.

### AK-008 Exports

Status: shipped in v0.6.0.

Generate weekly/monthly reports for personal review.

- CSV and JSON exports for project/task/session/model aggregates.
- Markdown weekly digest.
- Include source/pricing metadata and privacy statement.

Acceptance:

- `aikeeper export --format json|csv|markdown` emits metadata-only reports.
- Reports include task budget status.

### AK-009 OpenAI Admin Costs Import

Status: shipped in v0.6.0.

Optionally import official organization-level billing from the OpenAI Admin Costs
API when the user provides an admin key.

- Store only aggregate cost buckets.
- Make clear that official org costs do not automatically map to local Codex
  project/task/session attribution.

Acceptance:

- OpenAI Admin Costs payloads import into aggregate external cost buckets.
- CLI supports `aikeeper sync openai-costs` with `OPENAI_ADMIN_KEY`.

### AK-010 Claude Adapter

Status: shipped in v0.6.0.

Add a second provider adapter after Codex MVP stabilizes.

- Keep the same project/task/session/event model.
- Add provider-specific parser tests from local Claude metadata.

Acceptance:

- `aikeeper sync claude` imports local Claude JSONL metadata.
- Parser stores token counts, model, cwd, session id, and path only.

### AK-011 Privacy Audit

Status: shipped in v0.7.0.

Continuously verify that the local AI Keeper database remains metadata-only.

- Check schema for prompt/message/content-style columns.
- Sample text columns for raw chat JSON shapes without echoing values.
- Surface the result in CLI, API, and dashboard.

Acceptance:

- `aikeeper audit privacy --json` reports pass/fail without leaking sensitive
  values.
- `/api/audit/privacy` exposes the same result.
- Overview dashboard renders the privacy status.

### AK-012 Ingest Health

Status: shipped in v0.7.0.

Show whether local usage ingestion is complete and fresh.

- Count sessions, providers, token events, transcript paths, ingest offsets,
  missing sources, lagging sources, and unpriced model labels.
- Surface the result in CLI, API, and dashboard.

Acceptance:

- `aikeeper health ingest --json` reports source and model quality counts.
- `/api/health/ingest` exposes the same result.
- Overview dashboard renders ingest health.

## Now

All current backlog items are shipped. Next work should start from new feedback
or hardening tasks found while using the dashboard.
