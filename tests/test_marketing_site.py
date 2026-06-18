import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SITE_URL = "https://andrei.levk.in/ai-keeper/"


def test_readme_is_product_focused_and_points_to_user_paths() -> None:
    text = (REPO / "README.md").read_text(encoding="utf-8")

    assert text.startswith("# AI Keeper")
    assert "Turn AI agents from an open-ended burn rate into a managed engineering budget." in text
    assert "AI implementation cost per useful outcome" in text
    assert "## Why AI Keeper" in text
    assert "## What You Get" in text
    assert "## Install" in text
    assert "## Privacy Model" in text
    assert "Codex and Claude usage" in text
    assert "Workflow Harness" in text
    assert "aikeeper outcome done --status useful --type code" in text
    assert "Claude metadata import" in text
    assert "brew install alevkin/tap/aikeeper" in text
    assert "aikeeper sync claude --once" in text
    assert "uv run aikeeper" not in text
    assert "aikeeper-install --port 8766" in text
    assert "https://andrei.levk.in/ai-keeper/" in text
    assert "docs/user-guide.md" in text
    assert "docs/index.html" not in text
    assert "## Stack" not in text
    assert text.index("## Why AI Keeper") < text.index("## Install")


def test_github_pages_landing_is_static_product_page() -> None:
    index = REPO / "docs" / "index.html"
    styles = REPO / "docs" / "styles.css"
    preview = REPO / "docs" / "assets" / "dashboard-preview.svg"
    hook_preview = REPO / "docs" / "assets" / "codex-hook-preview.svg"

    html = index.read_text(encoding="utf-8")
    css = styles.read_text(encoding="utf-8")
    svg = preview.read_text(encoding="utf-8")
    hook_svg = hook_preview.read_text(encoding="utf-8")

    assert "<title>AI Keeper - AI Task Economics</title>" in html
    assert 'href="styles.css?v=20260618-nowrap-v2"' in html
    assert 'href="styles.css"' not in html
    assert 'src="assets/dashboard-preview.svg?v=' in html
    assert 'src="assets/codex-hook-preview.svg"' in html
    assert 'AI Keeper Codex hook summary preview' in html
    assert 'href="#features"' in html
    assert 'href="#privacy"' in html
    assert 'href="#install"' in html
    assert 'href="https://github.com/alevkin/ai-keeper"' in html
    assert "Turn AI agents into a managed engineering budget." in html
    assert "AI-assisted implementation task costs" in html
    assert "Task Economics" in html
    assert "Next best move" in html
    assert "Task Ledger" in html
    assert "Workflow Harness" in html
    assert "cache read and cache write tokens" in html
    assert 'id="codex-hook"' in html
    assert "Codex gets the usage line too" in html
    assert "<strong>AI Keeper</strong> | turn 125,770 tokens" not in html
    assert "session 237,711,203 tokens" not in html
    assert "turn $0.08 / 125.8K tokens" in html
    assert "next: narrow scope" in html
    assert "Install locally" in html
    assert "Trust the hooks in Codex Settings" in html
    assert "brew install alevkin/tap/aikeeper" in html
    assert "aikeeper-install --port 8766" in html
    assert 'data-copy-command="brew install alevkin/tap/aikeeper&#10;aikeeper-install --port 8766"' in html
    assert 'aria-label="Copy install command"' in html
    assert "navigator.clipboard.writeText(command)" in html
    assert "No prompts. No assistant messages. No raw transcript copies." in html
    assert "AI Keeper dashboard preview" in svg
    assert "Task Economics" in svg
    assert "Next best move" in svg
    assert "Active rate" in svg
    assert "This week" in svg
    assert "AI Keeper Codex hook summary preview" in hook_svg
    assert "AI Keeper" in hook_svg
    assert "turn $0.08 / 125.8K tok" in hook_svg
    assert "session 237,711,203 tokens" not in hook_svg
    assert "next: narrow scope" in hook_svg
    assert "Web preview" in hook_svg
    assert "Ask for follow-up changes" in hook_svg
    assert ".copy-command" in css
    assert ".hook-preview" in css
    assert ".hook-figure" in css
    assert ".codex-window" not in css
    assert "display: grid" in css
    assert "white-space: nowrap" in css
    assert "font-size: 92px" in css
    assert "font-size: clamp" not in css
    assert "grid-template-columns: minmax(500px, 0.9fr) minmax(0, 1.1fr)" in css
    assert "@media (max-width: 760px)" in css


def test_github_pages_landing_has_search_and_social_metadata() -> None:
    html = (REPO / "docs" / "index.html").read_text(encoding="utf-8")
    social_preview = REPO / "docs" / "assets" / "social-preview.png"
    image_url = f"{SITE_URL}assets/social-preview.png"

    assert f'<link rel="canonical" href="{SITE_URL}">' in html
    assert '<link rel="sitemap" type="application/xml" href="sitemap.xml">' in html
    assert '<meta name="robots" content="index,follow,max-image-preview:large">' in html
    assert '<meta name="author" content="Andrei Levkin">' in html
    assert '<meta name="theme-color" content="#157465">' in html
    assert f'<meta property="og:url" content="{SITE_URL}">' in html
    assert '<meta property="og:site_name" content="AI Keeper">' in html
    assert '<meta property="og:locale" content="en_US">' in html
    assert f'<meta property="og:image" content="{image_url}">' in html
    assert '<meta property="og:image:width" content="1200">' in html
    assert '<meta property="og:image:height" content="630">' in html
    assert '<meta property="og:image:alt" content="AI Keeper dashboard showing task economics for AI-assisted engineering work">' in html
    assert '<meta name="twitter:card" content="summary_large_image">' in html
    assert '<meta name="twitter:title" content="AI Keeper - AI Task Economics">' in html
    assert f'<meta name="twitter:image" content="{image_url}">' in html

    match = re.search(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, re.S)
    assert match, "landing page should include SoftwareApplication JSON-LD"
    structured_data = json.loads(match.group(1))
    assert structured_data["@context"] == "https://schema.org"
    assert structured_data["@type"] == "SoftwareApplication"
    assert structured_data["name"] == "AI Keeper"
    assert structured_data["url"] == SITE_URL
    assert structured_data["applicationCategory"] == "DeveloperApplication"
    assert structured_data["codeRepository"] == "https://github.com/alevkin/ai-keeper"
    assert structured_data["offers"] == {"@type": "Offer", "price": "0", "priceCurrency": "USD"}
    assert "AI implementation cost per useful outcome" in structured_data["description"]
    assert "Task Economics" in structured_data["featureList"]

    assert social_preview.exists()
    assert social_preview.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_github_pages_indexing_files_point_to_canonical_landing() -> None:
    robots = (REPO / "docs" / "robots.txt").read_text(encoding="utf-8")
    sitemap = REPO / "docs" / "sitemap.xml"

    assert "User-agent: *" in robots
    assert "Allow: /" in robots
    assert f"Sitemap: {SITE_URL}sitemap.xml" in robots

    root = ET.fromstring(sitemap.read_text(encoding="utf-8"))
    namespace = {"sitemap": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [loc.text for loc in root.findall("sitemap:url/sitemap:loc", namespace)]
    assert SITE_URL in locs
    assert f"{SITE_URL}user-guide.md" in locs


def test_markdown_user_guide_documents_primary_and_recovery_paths() -> None:
    guide = REPO / "docs" / "user-guide.md"
    text = guide.read_text(encoding="utf-8")

    assert text.startswith("# AI Keeper User Guide")
    assert "brew install alevkin/tap/aikeeper" in text
    assert "Run setup after Homebrew finishes" in text
    assert "starts the local service" in text
    assert "installs the Codex hooks" in text
    assert "Trust the hooks in Codex Settings" in text
    assert "aikeeper-install --port 8766" in text
    assert "aikeeper doctor --port 8766" in text
    assert "aikeeper sync claude --once" in text
    assert "uv run aikeeper" not in text
    assert "aikeeper install workflow-harness --repo-root ." in text
    assert "aikeeper outcome suggest --cwd . --json" in text
    assert "$CLAUDE_HOME/projects/**/*.jsonl" in text
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
