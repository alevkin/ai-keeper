# Repository Settings Checklist

These settings require owner action in the personal account before AI Keeper is
made public.

- Confirm the default branch is `main`.
- Enable branch protection for `main`.
- Require CI to pass before merging.
- Keep Actions permissions read-only by default.
- Review Actions permissions before allowing release publishing.
- Keep repository secrets empty until release automation needs them.
- Store signing keys outside the repository.
- Confirm the repository owner and package namespace are the intended personal account.
- Confirm visibility remains private until the public-release checklist passes.
- Review issue templates and private disclosure process before public launch.

Owner action is required for default branch, branch protection, Actions
permissions, repository visibility, and secret management. Avoid using an
unrelated organization or company account for these settings.
