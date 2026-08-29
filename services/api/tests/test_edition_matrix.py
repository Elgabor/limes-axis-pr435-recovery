from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT = REPO_ROOT / "scripts/check_edition_matrix.py"
MATRIX_PATH = REPO_ROOT / "docs/edition-capabilities.toml"
GENERATED_PATH = REPO_ROOT / "docs/editions-matrix.md"


def load_checker():
    spec = importlib.util.spec_from_file_location("check_edition_matrix", CHECK_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_edition_matrix_is_valid_complete_and_rendered() -> None:
    checker = load_checker()
    matrix = checker.load_matrix(MATRIX_PATH)

    assert checker.validate_matrix(matrix, REPO_ROOT) == []
    assert checker.render_matrix(matrix) == GENERATED_PATH.read_text(encoding="utf-8")
    assert checker.export_blockers(matrix) == []
    assert len(matrix["capabilities"]) == 41


def test_undecided_capability_blocks_export_readiness() -> None:
    checker = load_checker()
    matrix = checker.load_matrix(MATRIX_PATH)
    matrix["capabilities"][0]["disposition"] = "undecided"

    assert checker.export_blockers(matrix) == ["CORE-CONSOLE"]


def test_unknown_disposition_and_missing_area_fail_validation() -> None:
    checker = load_checker()
    matrix = checker.load_matrix(MATRIX_PATH)
    matrix["capabilities"][0]["disposition"] = "community-ish"
    matrix["capabilities"][0]["areas"] = ["missing/product-area"]
    for capability in matrix["capabilities"]:
        capability["areas"] = [
            area for area in capability["areas"] if area != "apps/web"
        ]

    errors = checker.validate_matrix(matrix, REPO_ROOT)

    assert any("disposition is invalid" in error for error in errors)
    assert any("path does not exist" in error for error in errors)
    assert any("repository area is not inventoried: apps/web" in error for error in errors)
