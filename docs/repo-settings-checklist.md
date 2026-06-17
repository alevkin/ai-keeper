# Repository Settings Checklist

These settings require owner action in the personal account before AI Keeper is
made public.

- Confirm the default branch is `main`. Current: done on 2026-06-17.
- Enable branch protection for `main`. Current: lightweight protection is
  enabled on 2026-06-17.
- Require CI to pass before merging. Current: deferred until the first public
  collaboration workflow.
- Keep Actions permissions read-only by default. Current: done.
- Review Actions permissions before allowing release publishing.
- Keep repository secrets empty unless a future workflow has a specific need.
- Release signing uses keyless `cosign`; do not add signing keys to repository
  secrets for the default flow.
- Confirm the repository owner and package namespace are the intended personal account.
- Confirm visibility remains private until the public-release checklist passes.
- Review issue templates before public launch. Current: metadata-only issue
  forms added in `.github/ISSUE_TEMPLATE/`.
- Confirm GitHub private vulnerability reporting is enabled before public
  launch, or keep `SECURITY.md` as the explicit private disclosure path.

Owner action is required for default branch, branch protection, Actions
permissions, repository visibility, and secret management. Avoid using an
unrelated organization or company account for these settings.

See [GitHub Operations Status](github-ops-status.md) for the latest verified
private-repository settings.
