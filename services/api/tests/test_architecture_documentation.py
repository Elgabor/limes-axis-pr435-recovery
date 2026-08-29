import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCAL_MARKDOWN_LINK = re.compile(
    r"(?<!!)\[[^\]]+\]\((?!https?://|mailto:|#)([^)#]+)(?:#[^)]+)?\)"
)
ARCHITECTURE_DOCS = [
    Path("docs/architecture.md"),
    Path("docs/architecture-changelog.md"),
]


@pytest.mark.parametrize("relative_path", ARCHITECTURE_DOCS)
def test_architecture_documentation_links_resolve(relative_path: Path) -> None:
    document = REPO_ROOT / relative_path
    targets = LOCAL_MARKDOWN_LINK.findall(document.read_text())

    assert targets, f"{relative_path} must link to its owning evidence"
    missing = [
        target
        for target in targets
        if not (document.parent / target.strip("<>")).resolve().exists()
    ]
    assert missing == [], f"{relative_path} has missing local links: {missing}"


def test_pull_request_template_requires_architecture_drift_review() -> None:
    template = (REPO_ROOT / ".github/PULL_REQUEST_TEMPLATE.md").read_text()

    assert "## Architecture drift" in template
    assert "docs/architecture.md" in template
    assert "docs/architecture-changelog.md" in template
