from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_readme_is_product_focused_and_points_to_user_paths() -> None:
    text = (REPO / "README.md").read_text(encoding="utf-8")

    assert text.startswith("# AI Keeper")
    assert "Understand your AI coding spend without giving up privacy." in text
    assert "## Why AI Keeper" in text
    assert "## What You Get" in text
    assert "## Install" in text
    assert "## Privacy Model" in text
    assert "brew install alevkin/tap/aikeeper" in text
    assert "brew install alevkin/tap/aikeeper\naikeeper-install --port 8766" not in text
    assert "https://andrei.levk.in/ai-keeper/" in text
    assert "docs/user-guide.md" in text
    assert "docs/index.html" not in text
    assert "## Stack" not in text
    assert text.index("## Why AI Keeper") < text.index("## Install")


def test_github_pages_landing_is_static_product_page() -> None:
    index = REPO / "docs" / "index.html"
    styles = REPO / "docs" / "styles.css"
    preview = REPO / "docs" / "assets" / "dashboard-preview.svg"

    html = index.read_text(encoding="utf-8")
    css = styles.read_text(encoding="utf-8")
    svg = preview.read_text(encoding="utf-8")

    assert "<title>AI Keeper" in html
    assert 'href="styles.css"' in html
    assert 'src="assets/dashboard-preview.svg"' in html
    assert 'href="#features"' in html
    assert 'href="#privacy"' in html
    assert 'href="#install"' in html
    assert 'href="https://github.com/alevkin/ai-keeper"' in html
    assert "Understand your AI coding spend without giving up privacy." in html
    assert "Install in one command" in html
    assert "brew install alevkin/tap/aikeeper" in html
    assert "aikeeper-install --port 8766" not in html
    assert 'data-copy-command="brew install alevkin/tap/aikeeper"' in html
    assert 'aria-label="Copy install command"' in html
    assert "navigator.clipboard.writeText(command)" in html
    assert "No prompts. No assistant messages. No raw transcript copies." in html
    assert "AI Keeper dashboard preview" in svg
    assert "Active rate" in svg
    assert "This week" in svg
    assert ".copy-command" in css
    assert "display: grid" in css
    assert "@media (max-width: 760px)" in css


def test_markdown_user_guide_documents_primary_and_recovery_paths() -> None:
    guide = REPO / "docs" / "user-guide.md"
    text = guide.read_text(encoding="utf-8")

    assert text.startswith("# AI Keeper User Guide")
    assert "brew install alevkin/tap/aikeeper" in text
    assert "starts the local service" in text
    assert "installs the Codex hooks" in text
    assert "aikeeper-install --port 8766" in text
    assert "does not store prompts" in text


def test_github_pages_workflow_deploys_docs_without_secrets() -> None:
    workflow = REPO / ".github" / "workflows" / "pages.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "name: GitHub Pages" in text
    assert "branches: [main]" in text
    assert "pages: write" in text
    assert "id-token: write" in text
    assert "actions/upload-pages-artifact@v3" in text
    assert "actions/deploy-pages@v4" in text
    assert "path: docs" in text
    assert "secrets." not in text
