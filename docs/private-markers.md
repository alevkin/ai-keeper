# Private Markers

AI Keeper keeps repository checks company-agnostic by loading private marker
rules from the developer machine, not from the repository.

Default path:

```bash
$AIKEEPER_HOME/private-markers.toml
```

If `AIKEEPER_HOME` is unset, AI Keeper uses `~/.aikeeper`. You can override the
file path with `AIKEEPER_PRIVATE_MARKERS`.

Example:

```toml
[[rules]]
id = "company-domain"
scope = "company"
literal = "company.example"

[[rules]]
id = "private-author-email"
scope = "company"
regex = "person[.]name@company[.]example"

[[rules]]
id = "internal-workspace"
scope = "project"
literal = "internal-workspace"
```

Rules support:

- `id`: stable rule id shown in audit output.
- `scope`: `company` or `project`.
- `literal`: exact marker to find.
- `regex`: regular expression marker to find.
- `ignore_case`: optional, defaults to `true`.
- `reason`: optional sanitized reason shown in audit output.

Audit results report paths, line numbers, scopes, and rule ids. They do not echo
the matched marker value.

Run checks manually:

```bash
aikeeper audit distribution --json
aikeeper audit public-release --tag v0.0.0 --dist-dir dist --allow-dirty --json
```

Install local git hooks for a developer checkout:

```bash
scripts/install-git-hooks.sh
```

The hooks run before commit and push. They read the same local private marker
config and do not write marker values into git-tracked files.
