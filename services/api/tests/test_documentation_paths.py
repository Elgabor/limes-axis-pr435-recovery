from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT = REPO_ROOT / "scripts" / "check_documentation_paths.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("check_documentation_paths", CHECK_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repository_documentation_paths_resolve() -> None:
    checker = load_checker()

    assert checker.broken_references(REPO_ROOT) == []


def test_checker_reports_inline_and_reference_style_missing_paths(tmp_path: Path) -> None:
    checker = load_checker()
    (tmp_path / "README.md").write_text(
        "[missing](docs/inline.md)\n[reference]: docs/reference.md\n",
        encoding="utf-8",
    )

    broken = checker.broken_references(tmp_path)

    assert [(item.line, item.target) for item in broken] == [
        (1, "docs/inline.md"),
        (2, "docs/reference.md"),
    ]


def test_checker_ignores_external_urls_and_local_anchors(tmp_path: Path) -> None:
    checker = load_checker()
    (tmp_path / "README.md").write_text(
        "[section](#section)\n[web](https://example.com/path)\n",
        encoding="utf-8",
    )

    assert checker.broken_references(tmp_path) == []
