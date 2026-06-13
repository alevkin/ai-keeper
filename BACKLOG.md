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

## Now

### AK-003 Budget Guards

Warn when a project, task, session, or turn approaches a configured token or USD
budget.

- Start with config-file budgets.
- Surface warnings in the dashboard and Codex hook summary.
- Keep enforcement soft in MVP: warn, do not block.

### AK-004 Task Budgets

Attach budgets to branch/task keys.

- Derive defaults from branch issue IDs when available.
- Show budget burn-down and remaining estimate.
- Export task budget status.

### AK-005 Context Bloat Tracker

Track context growth and caching health.

- Show input/cached-input/output split over time.
- Highlight drops in cached input ratio.
- Suggest when a session is likely ready for compaction or restart.

### AK-006 Anomaly Detection

Flag unusual turns.

- Detect large turns, sudden cost jumps, cache regressions, and model switches.
- Show anomalies on session and project pages.
- Include a concise reason for each anomaly.

### AK-007 Savings Simulator

Estimate what a project/task/session would have cost on another model.

- Use the same token events with a selected target model price.
- Compare actual estimate vs simulated estimate.
- Keep tool/hosting costs out until they are modeled explicitly.

### AK-008 Exports

Generate weekly/monthly reports for personal review.

- CSV and JSON exports for project/task/session/model aggregates.
- Markdown weekly digest.
- Include source/pricing metadata and privacy statement.

## Later

### AK-009 OpenAI Admin Costs Import

Optionally import official organization-level billing from the OpenAI Admin Costs
API when the user provides an admin key.

- Store only aggregate cost buckets.
- Make clear that official org costs do not automatically map to local Codex
  project/task/session attribution.

### AK-010 Claude Adapter

Add a second provider adapter after Codex MVP stabilizes.

- Keep the same project/task/session/event model.
- Add provider-specific parser tests from local Claude metadata.
