from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Callable

from aikeeper.audit import audit_privacy
from aikeeper.distribution import audit_distribution_readiness


CommandRunner = Callable[[list[str], Path], tuple[int, str, str]]

FORBIDDEN_AUTHOR_PATTERNS = (
    re.compile("private-company" + "private-company", re.IGNORECASE),
    re.compile(r"andrei\.levkin@", re.IGNORECASE),
)


def _run_command(command: list[str], cwd: Path) -> tuple[int, str, str]:
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _check(checks: list[dict[str, Any]], name: str, passed: bool, detail: str, **extra: Any) -> None:
    check = {"name": name, "status": "pass" if passed else "fail", "detail": detail}
    check.update(extra)
    checks.append(check)


def _git_output(repo_root: Path, runner: CommandRunner, *args: str) -> tuple[bool, str]:
    code, stdout, stderr = runner(["git", *args], repo_root)
    if code != 0:
        return False, stderr or stdout
    return True, stdout


def _latest_tag(repo_root: Path, runner: CommandRunner) -> str | None:
    ok, output = _git_output(repo_root, runner, "tag", "--list", "v*", "--sort=-v:refname")
    if not ok:
        return None
    return next((line.strip() for line in output.splitlines() if line.strip()), None)


def _read_pyproject_version(repo_root: Path) -> str | None:
    path = repo_root / "pyproject.toml"
    if not path.exists():
        return None
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    version = data.get("project", {}).get("version")
    return str(version) if version else None


def _read_manifest_version(repo_root: Path) -> str | None:
    path = repo_root / "packaging" / "manifest.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    version = data.get("version")
    return str(version) if version else None


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checksum_index_is_valid(dist_dir: Path) -> bool:
    path = dist_dir / "CHECKSUMS.txt"
    if not path.exists():
        return False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            return False
        expected = parts[0]
        filename = parts[-1].lstrip("*")
        target = dist_dir / filename
        if not target.exists() or _hash_file(target) != expected:
            return False
    return True


def _artifact_check(dist_dir: Path, tag: str) -> tuple[bool, str]:
    archive_name = f"aikeeper-{tag}.tar.gz"
    required = [
        archive_name,
        f"{archive_name}.sha256",
        "CHECKSUMS.txt",
        "SIGNING.md",
        "release-manifest.json",
    ]
    missing = [name for name in required if not (dist_dir / name).exists()]
    if missing:
        return False, f"missing artifact(s): {', '.join(missing)}"

    archive = dist_dir / archive_name
    archive_hash = _hash_file(archive)
    sha_text = (dist_dir / f"{archive_name}.sha256").read_text(encoding="utf-8")
    if archive_hash not in sha_text:
        return False, f"{archive_name}.sha256 does not match archive"
    if not _checksum_index_is_valid(dist_dir):
        return False, "CHECKSUMS.txt does not match artifacts"

    manifest = json.loads((dist_dir / "release-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != tag:
        return False, "release-manifest.json version does not match tag"
    if manifest.get("archive") != archive_name:
        return False, "release-manifest.json archive does not match tag"
    if manifest.get("metadata_only") is not True:
        return False, "release-manifest.json must declare metadata_only=true"
    return True, f"{len(required)} artifact(s) verified"


def _workflow_check(repo_root: Path) -> tuple[bool, str]:
    ci = repo_root / ".github" / "workflows" / "ci.yml"
    release = repo_root / ".github" / "workflows" / "release.yml"
    gate = repo_root / ".github" / "workflows" / "public-release-gate.yml"
    missing = [path.as_posix() for path in (ci, release, gate) if not path.exists()]
    if missing:
        return False, f"missing workflow(s): {', '.join(missing)}"

    release_text = release.read_text(encoding="utf-8")
    gate_text = gate.read_text(encoding="utf-8")
    if "gh release create" not in release_text:
        return False, "release workflow must create GitHub releases"
    if "secrets." in release_text or "secrets." in gate_text:
        return False, "release workflows must not depend on repository secrets"
    if "scripts/public-release-gate.sh" not in gate_text:
        return False, "public release gate workflow must run scripts/public-release-gate.sh"
    return True, "CI, release, and public gate workflows are present"


def _github_repo_from_remote(repo_root: Path, runner: CommandRunner) -> str | None:
    ok, output = _git_output(repo_root, runner, "config", "--get", "remote.origin.url")
    if not ok or not output:
        return None
    if output.startswith("git@github.com:"):
        return output.removeprefix("git@github.com:").removesuffix(".git")
    match = re.search(r"github\.com[:/](?P<repo>[^/]+/[^/.]+)", output)
    if match:
        return match.group("repo")
    return None


def _online_checks(
    *,
    repo_root: Path,
    github_repo: str,
    tag: str,
    runner: CommandRunner,
    checks: list[dict[str, Any]],
) -> None:
    code, stdout, stderr = runner(
        ["gh", "repo", "view", github_repo, "--json", "defaultBranchRef,visibility,isPrivate"],
        repo_root,
    )
    if code != 0:
        _check(checks, "github_repo", False, stderr or stdout or "gh repo view failed")
    else:
        data = json.loads(stdout)
        default_branch = data.get("defaultBranchRef", {}).get("name")
        passed = default_branch == "main" and data.get("isPrivate") is True
        _check(checks, "github_repo", passed, f"default={default_branch}, visibility={data.get('visibility')}")

    code, stdout, stderr = runner(
        ["gh", "release", "view", tag, "--repo", github_repo, "--json", "isDraft,isPrerelease,assets,url"],
        repo_root,
    )
    if code != 0:
        _check(checks, "github_release", False, stderr or stdout or "gh release view failed")
    else:
        data = json.loads(stdout)
        asset_names = {asset.get("name") for asset in data.get("assets", [])}
        required_assets = {
            f"aikeeper-{tag}.tar.gz",
            f"aikeeper-{tag}.tar.gz.sha256",
            "CHECKSUMS.txt",
            "SIGNING.md",
            "release-manifest.json",
        }
        passed = data.get("isDraft") is False and data.get("isPrerelease") is False and required_assets <= asset_names
        _check(checks, "github_release", passed, data.get("url") or "release metadata checked")

    code, stdout, stderr = runner(
        [
            "gh",
            "run",
            "list",
            "--repo",
            github_repo,
            "--workflow",
            "CI",
            "--branch",
            "main",
            "--status",
            "success",
            "--limit",
            "1",
            "--json",
            "databaseId,conclusion,status,displayTitle",
        ],
        repo_root,
    )
    if code != 0:
        _check(checks, "github_ci", False, stderr or stdout or "gh run list failed")
    else:
        runs = json.loads(stdout)
        _check(checks, "github_ci", bool(runs), "latest successful main CI run exists")


def evaluate_public_release_gate(
    *,
    repo_root: Path | str,
    db_path: Path | str,
    dist_dir: Path | str,
    tag: str | None = None,
    online: bool = False,
    github_repo: str | None = None,
    allow_dirty: bool = False,
    privacy_result: dict[str, Any] | None = None,
    distribution_result: dict[str, Any] | None = None,
    runner: CommandRunner = _run_command,
) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    db = Path(db_path).expanduser()
    dist = Path(dist_dir).expanduser().resolve()
    checks: list[dict[str, Any]] = []

    selected_tag = tag or _latest_tag(root, runner)
    if not selected_tag:
        _check(checks, "git_tag", False, "no v* tag found")
        selected_tag = "v0.0.0"
    else:
        latest_tag = _latest_tag(root, runner)
        _check(checks, "git_tag", latest_tag == selected_tag, f"selected={selected_tag}, latest={latest_tag}")

    version = selected_tag.removeprefix("v")
    pyproject_version = _read_pyproject_version(root)
    manifest_version = _read_manifest_version(root)
    _check(
        checks,
        "version_metadata",
        pyproject_version == version and manifest_version == version,
        f"pyproject={pyproject_version}, manifest={manifest_version}, tag={selected_tag}",
    )

    changelog = root / "CHANGELOG.md"
    changelog_ok = changelog.exists() and f"## {selected_tag}" in changelog.read_text(encoding="utf-8")
    _check(checks, "changelog", changelog_ok, f"CHANGELOG.md contains {selected_tag}")

    workflow_ok, workflow_detail = _workflow_check(root)
    _check(checks, "workflow_readiness", workflow_ok, workflow_detail)

    ok, status = _git_output(root, runner, "status", "--porcelain")
    worktree_ok = ok and (allow_dirty or not status.strip())
    _check(checks, "git_worktree_clean", worktree_ok, "dirty allowed" if allow_dirty else "worktree must be clean")

    ok, authors = _git_output(root, runner, "log", "--format=%an <%ae>")
    author_ok = ok and not any(pattern.search(authors) for pattern in FORBIDDEN_AUTHOR_PATTERNS)
    _check(checks, "git_author_history", author_ok, "no forbidden author markers found")

    privacy = privacy_result or audit_privacy(db)
    _check(checks, "privacy_audit", privacy.get("status") == "pass", f"status={privacy.get('status')}", result=privacy)

    distribution = distribution_result or audit_distribution_readiness(root)
    _check(
        checks,
        "distribution_audit",
        distribution.get("status") == "pass",
        f"status={distribution.get('status')}",
        result=distribution,
    )

    artifact_ok, artifact_detail = _artifact_check(dist, selected_tag)
    _check(checks, "release_artifacts", artifact_ok, artifact_detail)

    resolved_repo = github_repo
    if online:
        resolved_repo = github_repo or _github_repo_from_remote(root, runner)
        if not resolved_repo:
            _check(checks, "github_repo", False, "could not resolve GitHub repository")
        else:
            _online_checks(repo_root=root, github_repo=resolved_repo, tag=selected_tag, runner=runner, checks=checks)

    failed = [check for check in checks if check["status"] != "pass"]
    return {
        "status": "pass" if not failed else "fail",
        "release_ready": not failed,
        "tag": selected_tag,
        "online": online,
        "github_repo": resolved_repo,
        "checks": checks,
        "findings": failed,
    }
