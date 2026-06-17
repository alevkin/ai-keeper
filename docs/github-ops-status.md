# GitHub Operations Status

Last reviewed: 2026-06-17.

Repository: `alevkin/ai-keeper`

## Current Settings

- Default branch: `main`.
- Visibility: private.
- Actions: enabled.
- Workflow permissions: read-only by default.
- Pull request approval from workflows: disabled.
- `main` branch protection: enabled.
- `main` force-pushes: disabled.
- `main` deletions: disabled.
- Required PR reviews: not enabled yet.
- Required status checks: not enabled yet.

This is intentionally lightweight while the repository is private and maintained
by one owner. Tighten protection before a public launch or before accepting
external contributors.

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
gh api repos/alevkin/ai-keeper/actions/permissions
gh api repos/alevkin/ai-keeper/actions/permissions/workflow
gh api -X PUT repos/alevkin/ai-keeper/branches/main/protection --input <json>
gh run rerun 27707193999 --repo alevkin/ai-keeper
gh run watch 27707193999 --repo alevkin/ai-keeper --exit-status
```

Do not use a company GitHub account for owner-level settings on this repository.
