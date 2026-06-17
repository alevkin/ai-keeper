from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "output",
}

IGNORED_SUFFIXES = {
    ".db",
    ".jsonl",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
}

REQUIRED_DISTRIBUTION_FILES = [
    "README.md",
    "BACKLOG.md",
    "pyproject.toml",
    "uv.lock",
    "scripts/install.sh",
    "scripts/package.sh",
    "scripts/upgrade.sh",
    "scripts/rollback.sh",
    "packaging/manifest.json",
    "packaging/README.md",
    "packaging/macos/README.md",
]

_PRIVATE_USER = "Andrei" + "_Levkin"
_PRIVATE_WORKSPACE = "ng-" + "workspace"
_PRIVATE_WORKROOT = "/w/" + "tfs/"
_PRIVATE_COMPANY = "private-company" + "private-company"
_PRIVATE_KEY = "pers_" + "alevkin_260617"


@dataclass(frozen=True)
class DistributionRule:
    rule_id: str
    scope: str
    reason: str
    pattern: re.Pattern[str]


RULES = [
    DistributionRule(
        "private_user_path",
        "project",
        "contains a machine-specific absolute user path",
        re.compile(r"/Users/" + re.escape(_PRIVATE_USER) + r"\b"),
    ),
    DistributionRule(
        "private_workspace_name",
        "project",
        "contains a private workspace or adjacent project name",
        re.compile(r"(?:\b" + re.escape(_PRIVATE_WORKSPACE) + r"\b|" + re.escape(_PRIVATE_WORKROOT) + r")"),
    ),
    DistributionRule(
        "company_marker",
        "company",
        "contains a company-specific marker",
        re.compile(
            r"\b(?:"
            + re.escape(_PRIVATE_COMPANY)
            + r"|"
            + re.escape(_PRIVATE_COMPANY[:6] + " " + _PRIVATE_COMPANY[6:])
            + r"|"
            + re.escape(_PRIVATE_COMPANY + ".com")
            + r")\b",
            re.IGNORECASE,
        ),
    ),
    DistributionRule(
        "private_ssh_key_reference",
        "project",
        "contains a private SSH key path or key filename",
        re.compile(r"(?:^|/)\.ssh/|" + re.escape(_PRIVATE_KEY)),
    ),
]


def _run_git_files(repo_root: Path) -> list[Path] | None:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            timeout=2,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    raw_paths = [item for item in result.stdout.decode("utf-8", errors="replace").split("\0") if item]
    return [repo_root / raw_path for raw_path in raw_paths]


def _walk_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_root)
        if set(rel.parts) & IGNORED_DIRS:
            continue
        if path.suffix in IGNORED_SUFFIXES:
            continue
        files.append(path)
    return sorted(files)


def _candidate_files(repo_root: Path) -> list[Path]:
    git_files = _run_git_files(repo_root)
    if git_files is None:
        return _walk_files(repo_root)
    return sorted(path for path in git_files if path.exists() and path.is_file())


def _relative(repo_root: Path, path: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _scan_file(repo_root: Path, path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    findings: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for rule in RULES:
            if rule.pattern.search(line):
                findings.append(
                    {
                        "path": _relative(repo_root, path),
                        "line": line_number,
                        "rule": rule.rule_id,
                        "scope": rule.scope,
                        "reason": rule.reason,
                    }
                )
    return findings


def _manifest_findings(repo_root: Path) -> list[dict[str, Any]]:
    path = repo_root / "packaging" / "manifest.json"
    if not path.exists():
        return [
            {
                "path": "packaging/manifest.json",
                "rule": "missing_distribution_manifest",
                "scope": "distribution",
                "reason": "distribution manifest is required",
            }
        ]
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [
            {
                "path": "packaging/manifest.json",
                "rule": "invalid_distribution_manifest",
                "scope": "distribution",
                "reason": "distribution manifest is not valid JSON",
            }
        ]
    findings: list[dict[str, Any]] = []
    for key in ("local_only", "metadata_only"):
        if manifest.get(key) is not True:
            findings.append(
                {
                    "path": "packaging/manifest.json",
                    "rule": f"manifest_{key}_not_true",
                    "scope": "distribution",
                    "reason": f"packaging manifest must declare {key}=true",
                }
            )
    return findings


def _required_file_findings(repo_root: Path) -> list[dict[str, Any]]:
    findings = []
    for rel_path in REQUIRED_DISTRIBUTION_FILES:
        if not (repo_root / rel_path).exists():
            findings.append(
                {
                    "path": rel_path,
                    "rule": "missing_required_file",
                    "scope": "distribution",
                    "reason": "required distribution file is missing",
                }
            )
    return findings


def audit_distribution_readiness(repo_root: Path | str) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    files = _candidate_files(root)
    findings: list[dict[str, Any]] = []

    for path in files:
        findings.extend(_scan_file(root, path))
    findings.extend(_manifest_findings(root))
    findings.extend(_required_file_findings(root))

    company_findings = [finding for finding in findings if finding["scope"] == "company"]
    project_findings = [finding for finding in findings if finding["scope"] == "project"]
    contract_findings = [finding for finding in findings if finding["scope"] == "distribution"]

    return {
        "status": "pass" if not findings else "fail",
        "project_agnostic": not project_findings,
        "company_agnostic": not company_findings,
        "metadata_only": not contract_findings,
        "local_only": not contract_findings,
        "checks": {
            "repo_name": root.name,
            "tracked_files": len(files),
            "rules": [rule.rule_id for rule in RULES],
            "required_files": REQUIRED_DISTRIBUTION_FILES,
        },
        "findings": findings,
    }
