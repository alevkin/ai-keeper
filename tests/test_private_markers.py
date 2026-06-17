import json
from pathlib import Path

from aikeeper.distribution import REQUIRED_DISTRIBUTION_FILES, audit_distribution_readiness
from aikeeper.private_markers import default_private_markers_path, load_private_marker_rules


def _write_distribution_contract(repo: Path) -> None:
    for rel_path in REQUIRED_DISTRIBUTION_FILES:
        path = repo / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if rel_path == "packaging/manifest.json":
            path.write_text('{"local_only": true, "metadata_only": true}\n', encoding="utf-8")
        else:
            path.write_text(f"{rel_path}\n", encoding="utf-8")


def test_private_marker_rules_load_from_aikeeper_home(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    marker_path = home / "private-markers.toml"
    marker_path.parent.mkdir()
    marker_path.write_text(
        """
[[rules]]
id = "company-domain"
scope = "company"
literal = "company.example"

[[rules]]
id = "private-email"
scope = "company"
regex = "person[.]name@company[.]example"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIKEEPER_HOME", str(home))

    rules = load_private_marker_rules()

    assert default_private_markers_path() == marker_path
    assert [rule.rule_id for rule in rules] == ["company-domain", "private-email"]
    assert all(rule.scope == "company" for rule in rules)


def test_distribution_audit_uses_external_private_markers_without_echoing_values(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_distribution_contract(repo)
    marker_path = tmp_path / "private-markers.toml"
    marker_path.write_text(
        """
[[rules]]
id = "company-domain"
scope = "company"
literal = "company.example"

[[rules]]
id = "project-code"
scope = "project"
literal = "internal-workspace"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text(
        "Contact company.example before publishing internal-workspace notes.\n",
        encoding="utf-8",
    )

    result = audit_distribution_readiness(repo, private_markers_path=marker_path)
    serialized = json.dumps(result)

    assert result["status"] == "fail"
    assert result["company_agnostic"] is False
    assert result["project_agnostic"] is False
    assert "README.md" in serialized
    assert "company-domain" in serialized
    assert "project-code" in serialized
    assert "company.example" not in serialized
    assert "internal-workspace" not in serialized
    assert result["checks"]["private_marker_rules"] == 2
