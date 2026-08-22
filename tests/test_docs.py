"""Unit and regression tests for project documentation."""

from __future__ import annotations

import pathlib
import re
import urllib.parse

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_contributing_doc_exists() -> None:
    """Verify that docs/CONTRIBUTING.md exists and is not empty."""
    contributing_path = REPO_ROOT / "docs" / "CONTRIBUTING.md"
    assert contributing_path.is_file(), "docs/CONTRIBUTING.md does not exist"
    content = contributing_path.read_text(encoding="utf-8")
    assert len(content.strip()) > 0, "docs/CONTRIBUTING.md is empty"


def test_readme_references_contributing_doc() -> None:
    """Verify that README.md links to docs/CONTRIBUTING.md."""
    readme_path = REPO_ROOT / "README.md"
    assert readme_path.is_file(), "README.md does not exist"
    content = readme_path.read_text(encoding="utf-8")
    assert "docs/CONTRIBUTING.md" in content, (
        "README.md must link to docs/CONTRIBUTING.md"
    )


def test_contributing_branch_naming_convention() -> None:
    """Verify that docs/CONTRIBUTING.md specifies branch naming convention."""
    contributing_path = REPO_ROOT / "docs" / "CONTRIBUTING.md"
    content = contributing_path.read_text(encoding="utf-8")
    assert "dsh/<issue-id>" in content, (
        "docs/CONTRIBUTING.md must specify dsh/<issue-id> branch convention"
    )


def test_contributing_commit_conventions() -> None:
    """Verify that docs/CONTRIBUTING.md specifies commit conventions."""
    contributing_path = REPO_ROOT / "docs" / "CONTRIBUTING.md"
    content = contributing_path.read_text(encoding="utf-8")
    assert "Conventional Commits" in content, (
        "docs/CONTRIBUTING.md must mention Conventional Commits"
    )
    for commit_type in ("feat", "fix", "docs", "test"):
        assert commit_type in content, (
            f"docs/CONTRIBUTING.md must mention commit type '{commit_type}'"
        )


def test_contributing_testing_commands() -> None:
    """Verify that docs/CONTRIBUTING.md specifies testing commands."""
    contributing_path = REPO_ROOT / "docs" / "CONTRIBUTING.md"
    content = contributing_path.read_text(encoding="utf-8")
    assert "uv run pytest -v" in content, (
        "docs/CONTRIBUTING.md must document 'uv run pytest -v' command"
    )


def test_architecture_section_present() -> None:
    """Verify that architecture quick-reference is present in both docs."""
    contributing_path = REPO_ROOT / "docs" / "CONTRIBUTING.md"
    contributing_content = contributing_path.read_text(encoding="utf-8")
    assert "Architecture Quick-Reference" in contributing_content or (
        "Architecture" in contributing_content
    )

    readme_path = REPO_ROOT / "README.md"
    readme_content = readme_path.read_text(encoding="utf-8")
    assert "Architecture" in readme_content


def _extract_markdown_links(text: str) -> list[tuple[str, str]]:
    """Extract (link_text, link_target) pairs from markdown text."""
    # Matches [text](url_or_path)
    pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    return pattern.findall(text)


def _slugify_heading(heading: str) -> str:
    """Convert markdown heading text to github-style anchor slug."""
    # Lowercase, remove formatting characters, replace spaces with hyphens
    slug = heading.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    return slug


def test_markdown_links_resolve() -> None:
    """Verify that markdown relative links in documentation resolve properly."""
    doc_files = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "CONTRIBUTING.md",
    ]

    for doc_path in doc_files:
        assert doc_path.is_file(), f"{doc_path} must exist"
        content = doc_path.read_text(encoding="utf-8")
        links = _extract_markdown_links(content)

        # Collect headings for internal anchor link validation
        heading_lines = [
            line.lstrip("#").strip()
            for line in content.splitlines()
            if line.startswith("#")
        ]
        heading_slugs = {_slugify_heading(h) for h in heading_lines}

        for text, target in links:
            target = target.strip()
            if target.startswith("http://") or target.startswith("https://"):
                # External URL: check valid URL format
                parsed = urllib.parse.urlparse(target)
                assert parsed.scheme in ("http", "https"), f"Invalid external URL in {doc_path}: {target}"
                assert parsed.netloc, f"Invalid netloc for external URL in {doc_path}: {target}"
            elif target.startswith("#"):
                # Internal anchor link: check target anchor exists
                anchor = target.lstrip("#")
                assert anchor in heading_slugs, (
                    f"Anchor '#{anchor}' in {doc_path} does not match any heading. "
                    f"Available headings: {heading_slugs}"
                )
            else:
                # Relative file path (optionally with anchor #)
                file_part, _, anchor_part = target.partition("#")
                resolved_target = (doc_path.parent / file_part).resolve()
                assert resolved_target.exists(), (
                    f"Relative link '{target}' in {doc_path} resolves to non-existent path '{resolved_target}'"
                )
