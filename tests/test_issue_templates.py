from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
ISSUE_TEMPLATE_DIR = REPO / ".github" / "ISSUE_TEMPLATE"


def test_public_issue_forms_are_present_and_privacy_first() -> None:
    expected = {
        "config.yml",
        "bug_report.yml",
        "feature_request.yml",
        "security_contact.yml",
    }

    assert expected <= {path.name for path in ISSUE_TEMPLATE_DIR.glob("*.yml")}

    config = (ISSUE_TEMPLATE_DIR / "config.yml").read_text(encoding="utf-8")
    bug = (ISSUE_TEMPLATE_DIR / "bug_report.yml").read_text(encoding="utf-8")
    feature = (ISSUE_TEMPLATE_DIR / "feature_request.yml").read_text(encoding="utf-8")
    security = (ISSUE_TEMPLATE_DIR / "security_contact.yml").read_text(encoding="utf-8")

    assert "blank_issues_enabled: false" in config
    assert "https://github.com/alevkin/ai-keeper/security/policy" in config

    for text in (bug, feature, security):
        assert "name:" in text
        assert "description:" in text
        assert "body:" in text
        assert "metadata-only" in text
        assert "prompts, assistant messages, raw transcripts, API keys, or local database files" in text

    assert "labels: [bug, triage]" in bug
    assert "labels: [enhancement, triage]" in feature
    assert "labels: [security, triage]" in security
    assert "Do not report vulnerabilities in a public issue" in security
