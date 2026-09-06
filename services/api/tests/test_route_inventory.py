"""Keep the published operation ownership map tied to the running API contract."""

import runpy
from pathlib import Path

from axis_api.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_route_inventory_matches_registered_operations_and_domain_owners() -> None:
    exporter = runpy.run_path(str(REPO_ROOT / "services/api/scripts/export_route_inventory.py"))
    schema = create_app().openapi()
    source_root = REPO_ROOT / "services/api/src/axis_api"
    rendered = exporter["render_inventory"](schema, source_root)
    assert (REPO_ROOT / "docs/api-route-inventory.md").read_text() == rendered
    rows = exporter["inventory"](schema, source_root)
    model_rows = [row for row in rows if row["domain"] == "models"]
    assert len(model_rows) == 10
    assert {row["owner"] for row in model_rows} == {"routes/models.py"}
    assert {row["path"] for row in model_rows if row["deprecated"]} == {
        "/demo/manufacturing/model-routing",
    }
