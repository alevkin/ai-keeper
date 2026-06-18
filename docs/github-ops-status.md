# GitHub Operations Status

Last reviewed: 2026-06-18.

Repository: `alevkin/ai-keeper`

## Current Settings

- Default branch: `main`.
- Visibility: public as of 2026-06-18.
- Homepage: `https://andrei.levk.in/ai-keeper/`.
- Topics: `ai`, `claude`, `codex`, `developer-tools`, `local-first`,
  `tokens`.
- Actions: enabled.
- Workflow permissions: read-only by default.
- Pull request approval from workflows: disabled.
- Secret scanning: enabled.
- Secret scanning push protection: enabled.
- Private vulnerability reporting: enabled.
- Wiki: disabled.
- Projects: disabled.
- Delete branch on merge: enabled.
- `main` branch protection: enabled.
- `main` force-pushes: disabled.
- `main` deletions: disabled.
- Required PR reviews: not enabled yet.
- Required status checks: not enabled yet.

This is intentionally lightweight for the first public beta while the repository
is maintained by one owner. Tighten protection before accepting external
contributors.

## Public Launch

Public switch completed on 2026-06-18 after `scripts/public-release-gate.sh
--version v0.30.0 --output-dir dist --online` passed. The `alevkin/homebrew-tap`
repository is also public and points to AI Keeper `v0.30.0`.

## CI Follow-Up

The first CI failures on `main` and `agent/ak-ops-wave` had no job steps and no
runner assigned. After the personal GitHub Actions minute limit was resolved,
rerunning the `main` workflow completed successfully.

Verified run:

- Workflow: `CI`.
- Branch: `main`.
- Run id: `27707193999`.
- Result after rerun: success.

## Commands Used

```bash
gh repo edit alevkin/ai-keeper --default-branch main
gh repo edit alevkin/ai-keeper --visibility public --accept-visibility-change-consequences
gh repo edit alevkin/homebrew-tap --visibility public --accept-visibility-change-consequences
gh api repos/alevkin/ai-keeper/actions/permissions
gh api repos/alevkin/ai-keeper/actions/permissions/workflow
gh api -X PUT repos/alevkin/ai-keeper/branches/main/protection --input <json>
gh api -X PUT repos/alevkin/ai-keeper/private-vulnerability-reporting
gh run rerun 27707193999 --repo alevkin/ai-keeper
gh run watch 27707193999 --repo alevkin/ai-keeper --exit-status
```

Do not use a company GitHub account for owner-level settings on this repository.
