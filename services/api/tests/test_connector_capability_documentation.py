"""Keep the connector audit's executable evidence and live adapter inventory current."""

import ast
import re
from pathlib import Path

from axis_api import connector_execution
from axis_api.connector_s3_source import S3ObjectSource

REPO_ROOT = Path(__file__).resolve().parents[3]
MATRIX = REPO_ROOT / "docs/connector-capabilities.md"


def test_capability_matrix_covers_the_wired_source_connector_ids() -> None:
    live_ids = {
        value for name, value in vars(connector_execution).items()
        if name.endswith("_LIVE_SYNC_CONNECTOR_ID")
    }
    inventory = MATRIX.read_text().split("## Source families actually wired\n", 1)[1]
    inventory = inventory.split("## Capability matrix\n", 1)[0]
    documented_ids = set(re.findall(r"^\| `([^`]+)` \|", inventory, re.MULTILINE))
    assert documented_ids == live_ids | {S3ObjectSource.descriptor.connector_id}


def test_capability_evidence_selectors_still_resolve() -> None:
    selectors = re.findall(
        r"`(services/(?:api|worker)/tests/[^`]+\.py)::(test_\w+)`", MATRIX.read_text()
    )
    assert selectors, "The matrix must cite executable tests for its capability claims"
    for path, name in selectors:
        module = ast.parse((REPO_ROOT / path).read_text())
        functions = {
            node.name for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert name in functions, f"Stale capability evidence: {path}::{name}"
