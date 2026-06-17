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

### AK-013 Ingest Health Details

Status: shipped in v0.7.1.

Make ingest warnings actionable.

- Show missing transcript paths with provider, session id, project, task, cwd,
  and model metadata.
- Show missing and lagging source paths with offsets and byte lag.
- Keep details metadata-only; never read or display transcript contents.

Acceptance:

- `aikeeper health ingest --json` exposes `transcripts.missing_paths` and
  `ingest_state.problem_sources`.
- Overview dashboard renders detailed missing transcript and source sections.

### AK-014 DB Budget Settings UI

Status: shipped in v0.8.0.

Configure budget guards from the dashboard and store them in SQLite.

- Add `budget_settings` storage for default and task-level limits.
- Use database budgets by default across dashboard, hooks, exports, and status.
- Keep `budgets.toml` available only as an explicit legacy override.

Acceptance:

- Overview budget warnings use DB settings when no `budget_path` is passed.
- Dashboard form updates default budgets and current task overrides.
- `/api/budgets` exposes the stored DB config.

### AK-015 Observable System Jobs

Status: shipped in v0.15.0.

Make local repair and diagnostic actions observable from the dashboard.

- Store system jobs as metadata-only SQLite rows.
- Track queued, running, ok, and fail states.
- Keep command output bounded and scrubbed of chat content.

Acceptance:

- System actions can be queued and run through the CLI/server.
- Diagnostics page shows recent jobs and result state.
- Tests cover job persistence and output tail behavior.

### AK-016 Local Packaging Channel

Status: shipped in v0.16.0.

Build a portable local release package.

- Generate a source archive, sha256 file, release manifest, and local Homebrew
  formula.
- Install wrapper commands for install, upgrade, and rollback.
- Exclude runtime state, local databases, transcripts, logs, `.git`, `.venv`,
  `.vscode`, `dist`, and `output`.

Acceptance:

- `scripts/package.sh --version <tag>` creates all release artifacts.
- The generated Homebrew formula validates and points at the local archive.
- Tests verify excluded paths and generated release metadata.

### AK-017 Distribution Readiness Audit

Status: shipped in v0.17.0.

Verify that AI Keeper is project/company agnostic before publishing.

- Add `.vscode/` to ignored local editor state.
- Scan tracked release files for private machine paths, adjacent project names,
  company markers, and private SSH key references.
- Check the packaging contract still declares local-only and metadata-only.
- Report findings without echoing matched private values.

Acceptance:

- `aikeeper audit distribution --json` reports pass/fail.
- Current repo passes as project-agnostic, company-agnostic, local-only, and
  metadata-only.
- Tests cover both passing repo state and synthetic private-marker failures.

### AK-018 Private GitHub Publication Channel

Status: shipped in v0.18.0.

Publish the private repository without baking local secrets into the project.

- Add a publish script that accepts an explicit SSH key path.
- Configure local git author metadata for personal publishing.
- Run distribution audit before push.
- Set or update the `origin` remote and push current HEAD plus tags.
- Document the private repository channel while keeping the repository
  company-agnostic.

Acceptance:

- `scripts/publish.sh --dry-run` shows the remote, author, branch, audit, and
  SSH-key scoped push commands.
- Packaging manifest documents the private repository and publish script.
- The source archive and Homebrew formula point at the GitHub project homepage.

### AK-019 Public Release Hygiene

Status: shipped in v0.19.0.

Prepare the repository for a future public switch.

- Add license, security policy, contributing guide, privacy statement, and
  public-readiness checklist.
- Keep docs explicit about local-only and metadata-only behavior.
- Keep public-release checks runnable before repository visibility changes.

Acceptance:

- `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `PRIVACY.md`, and
  `docs/public-release-checklist.md` are present.
- Docs tell contributors not to store prompts, assistant messages, raw
  transcripts, or local databases.
- Tests verify required public-release docs exist.

### AK-020 Signed Release Artifacts

Status: shipped in v0.19.0.

Create verification materials for release artifacts.

- Generate `CHECKSUMS.txt` during packaging.
- Add `scripts/sign-release.sh` for checksum refresh and optional
  `cosign`/`minisign` signatures.
- Document verification commands without storing signing keys.

Acceptance:

- Package output includes `CHECKSUMS.txt`.
- `scripts/sign-release.sh --signer none` writes `CHECKSUMS.txt` and
  `SIGNING.md`.
- Dry-run signature mode shows the external signing command.

### AK-021 Homebrew Tap Path

Status: shipped in v0.19.0.

Prepare a tap-ready Homebrew layout.

- Generate `dist/homebrew-tap/Formula/aikeeper.rb` beside the local formula.
- Keep the formula source archive based until a public asset URL is available.
- Document the future tap migration path.

Acceptance:

- Package output contains the tap-ready formula.
- Packaging manifest exposes the tap formula target.
- Tests verify formula generation.

### AK-022 macOS App/DMG Research Spike

Status: shipped in v0.19.0.

Prototype a thin macOS installer wrapper without duplicating install logic.

- Add `packaging/macos/dmg/Aikeeper Installer.command`.
- Keep the wrapper delegated to `scripts/install.sh`.
- Document that local databases, logs, diagnostics, and transcripts stay out of
  the installer.

Acceptance:

- Wrapper references `scripts/install.sh`.
- Wrapper does not duplicate `aikeeper install all` internals.
- DMG notes document the packaging boundary.

### AK-023 Windows Service Prep

Status: shipped in v0.19.0.

Document the future Windows service path.

- Add Windows packaging notes for Codex on Windows.
- Add a dry-run PowerShell service-prep skeleton.
- Keep Windows support marked as not implemented until tested on Windows.

Acceptance:

- `packaging/windows/README.md` explains constraints and metadata-only behavior.
- `packaging/windows/install-service.ps1 -DryRun` sketches the daemon command.
- Tests verify the docs and dry-run script surface.

### AK-024 GitHub CI

Status: shipped in v0.20.0.

Run metadata-only release checks in GitHub Actions.

- Add CI for tests, privacy audit, distribution audit, package build, checksum
  verification, and Homebrew formula syntax.
- Keep workflow permissions read-only and avoid repository secrets.
- Keep Python version explicit.

Acceptance:

- `.github/workflows/ci.yml` runs on push, pull request, and manual dispatch.
- CI runs `uv run pytest -q`, `aikeeper audit privacy`, and
  `aikeeper audit distribution`.
- CI builds package artifacts, refreshes verification materials, verifies
  checksums, and validates both Homebrew formula layouts.

## Now

Next distribution/operations wave:

- AK-025 Release Automation: generate release notes and package artifacts from
  a tag without using local secrets.
- AK-026 Repo Settings Checklist: document private-to-public GitHub settings
  that still require owner action, including default branch, Actions
  permissions, branch protection, and secret management.
- AK-027 Update Channel UX: show installed version, latest local tag, and
  upgrade path in the System page.
- AK-028 Installer Preflight Hardening: make install/package scripts report
  missing tools and unsupported platforms more clearly.
