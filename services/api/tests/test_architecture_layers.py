"""Architecture guards are offline and parse source without importing application code."""

import copy
import importlib.util
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/check_architecture_layers.py"
spec = importlib.util.spec_from_file_location("architecture_layers_check", SCRIPT)
assert spec is not None and spec.loader is not None
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


@pytest.fixture
def inventory():
    return json.loads((REPO_ROOT / "docs/architecture-layers.json").read_text())


@pytest.fixture
def source_root(tmp_path):
    for name in checker.CORE_ROOTS:
        (tmp_path / name).mkdir(parents=True)
    return tmp_path


def write_source(root, code, path="services/api/src/axis_api/example.py"):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(code)
    return file


def test_current_inventory_import_budget_and_render_are_consistent(inventory):
    assert checker.validate_inventory(inventory, REPO_ROOT) == []
    edges, errors, count = checker.inspect_imports(REPO_ROOT)
    assert errors == []
    assert count >= 1
    assert checker.validate_import_budget(inventory, edges) == []
    generated = REPO_ROOT / "docs/architecture-layers-inventory.md"
    assert generated.read_text() == checker.render_inventory(inventory)


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda i: i["layers"].pop("trust"), "seven architecture layers"),
        (lambda i: i["layers"]["data"].pop("tenancy"), "missing tenancy"),
        (lambda i: i["components"].append(copy.deepcopy(i["components"][0])), "unique"),
        (lambda i: i["components"][0].update(owner="unowned"), "valid owner"),
        (lambda i: i["components"][0].update(dependencies=["trust"]), "self dependency"),
        (lambda i: i["components"][0].update(dependencies=["unknown"]), "dependencies"),
        (lambda i: i["components"][0].update(path="../outside"), "inside repository"),
        (lambda i: i["components"].pop(0), "service/package inventory"),
        (lambda i: i["issues"].pop(), "complete recorded"),
        (lambda i: i["issues"].append(copy.deepcopy(i["issues"][0])), "unique positive"),
        (lambda i: i["issues"][0].update(owner="two-layers"), "valid owner"),
        (lambda i: i["open_issue_snapshot"].update(captured_at="not-a-date"), "YYYY-MM-DD"),
        (lambda i: i["ports"].clear(), "public ports"),
        (lambda i: i["ports"][0].update(status="live-certified"), "owner/status"),
        (lambda i: i["ports"][0].update(evidence="../outside"), "repository file"),
        (lambda i: i["ports"][0].pop("failure"), "missing failure"),
    ],
)
def test_incomplete_or_ambiguous_ownership_is_rejected(inventory, mutation, reason):
    mutation(inventory)
    assert any(reason in error for error in checker.validate_inventory(inventory, REPO_ROOT))


def test_fresh_issue_check_cannot_claim_unmapped_coverage(inventory):
    live = [{"number": issue["number"]} for issue in inventory["issues"]]
    assert checker.validate_inventory(inventory, REPO_ROOT, live) == []
    live.append({"number": 999_999})
    assert any(
        "unmapped currently open issues" in error
        for error in checker.validate_inventory(inventory, REPO_ROOT, live)
    )


@pytest.mark.parametrize("new_manifest", ["pyproject.toml", "package.json"])
def test_new_service_manifest_requires_ownership(tmp_path, inventory, new_manifest):
    for item in inventory["components"]:
        if item["kind"] not in {"service", "package"}:
            continue
        folder = tmp_path / item["path"]
        folder.mkdir(parents=True)
        manifest = "package.json" if item["path"] in {"apps/web", "packages/schemas"} else (
            "pyproject.toml"
        )
        (folder / manifest).write_text("")
    before = checker.validate_inventory(inventory, tmp_path)
    assert not any("service/package inventory" in error for error in before)
    path = tmp_path / "services/new-service" / new_manifest
    path.parent.mkdir(parents=True)
    path.write_text("")
    after = checker.validate_inventory(inventory, tmp_path)
    assert any("service/package inventory" in error for error in after)


@pytest.mark.parametrize(
    "code,target",
    [
        ("import axis_verticals.logistics as sector", "axis_verticals.logistics"),
        ("from axis_packs import logistics", "axis_packs.logistics"),
        ("from axis_api import manufacturing_metadata", "axis_api.manufacturing_metadata"),
        (
            "from .manufacturing_metadata import operational_provenance as provenance",
            "axis_api.manufacturing_metadata.operational_provenance",
        ),
        (
            "if False:\n    from axis_api.demo import ApprovalDecision",
            "axis_api.demo.ApprovalDecision",
        ),
        ("from axis_api.demo import *", "axis_api.demo.*"),
    ],
)
def test_core_imports_cannot_gain_vertical_dependencies(source_root, code, target):
    write_source(source_root, code)
    edges, errors, _ = checker.inspect_imports(source_root)
    assert errors == []
    assert edges == Counter({("services/api/src/axis_api/example.py", target): 1})
    assert checker.validate_import_budget({}, edges)


def test_nested_relative_import_resolves_to_same_edge(source_root):
    write_source(
        source_root,
        "from ..demo import ApprovalDecision",
        "services/api/src/axis_api/routes/example.py",
    )
    edges, errors, _ = checker.inspect_imports(source_root)
    assert errors == []
    assert list(edges)[0][1] == "axis_api.demo.ApprovalDecision"


def test_relative_package_init_and_worker_sdk_are_covered(source_root):
    write_source(
        source_root,
        "from ..demo import ApprovalDecision",
        "services/api/src/axis_api/routes/__init__.py",
    )
    write_source(
        source_root,
        "from axis_packs.logistics import Client",
        "services/worker/src/axis_worker/example.py",
    )
    write_source(
        source_root,
        "import axis_verticals.logistics",
        "packages/sdk-python/src/axis_sdk/example.py",
    )
    edges, errors, count = checker.inspect_imports(source_root)
    assert errors == []
    assert count == 3
    assert sum(edges.values()) == 3


def test_new_core_package_is_scanned_without_a_manual_root_allowlist(source_root):
    write_source(
        source_root, "import axis_verticals.logistics", "packages/new-core/src/axis_new/example.py"
    )
    edges, errors, _ = checker.inspect_imports(source_root)
    assert errors == []
    assert sum(edges.values()) == 1


@pytest.mark.parametrize(
    "code",
    [
        "import importlib as loader\nloader.import_module('axis_verticals.logistics')",
        "from importlib import import_module as load\nload('axis_packs.logistics')",
        "__import__('axis_verticals.logistics')",
        "from builtins import __import__ as load\nload('axis_packs.logistics')",
        "import builtins\nbuiltins.__import__('axis_packs.logistics')",
    ],
)
def test_dynamic_loading_requires_explicit_architecture_review(source_root, code):
    write_source(source_root, code)
    _, errors, _ = checker.inspect_imports(source_root)
    assert any("dynamic loading" in error for error in errors)


def test_new_vertical_module_cannot_hide_inside_core(source_root):
    write_source(source_root, "value = 1", "services/api/src/axis_api/verticals/logistics.py")
    _, errors, _ = checker.inspect_imports(source_root)
    assert any("new vertical module" in error for error in errors)


def test_legacy_vertical_internal_import_does_not_become_shared_core_budget(source_root):
    write_source(
        source_root,
        "from axis_api.demo import ManufacturingOverview",
        "services/api/src/axis_api/demo_reference.py",
    )
    edges, errors, _ = checker.inspect_imports(source_root)
    assert edges == {}
    assert errors == []


def test_guard_never_imports_or_executes_runtime_sources(source_root):
    write_source(source_root, "raise RuntimeError('must never execute')\nimport json")
    edges, errors, count = checker.inspect_imports(source_root)
    assert edges == {}
    assert errors == []
    assert count == 1


def test_invalid_source_and_symlink_fail_closed(source_root):
    write_source(source_root, "def broken(")
    real = write_source(source_root, "value = 1", "services/api/src/axis_api/real.py")
    real.with_name("linked.py").symlink_to(real)
    _, errors, _ = checker.inspect_imports(source_root)
    assert any("cannot parse" in error for error in errors)
    assert any("symlink" in error for error in errors)


def test_legacy_budget_detects_growth_removal_and_duplicate_records():
    source = "services/api/src/axis_api/example.py"
    target = "axis_api.demo.ApprovalDecision"
    record = {"source": source, "targets": {target: 1}}
    inventory = {"legacy_imports": [record]}
    assert checker.validate_import_budget(inventory, Counter({(source, target): 1})) == []
    assert (
        "new core-to-vertical"
        in checker.validate_import_budget(
            inventory,
            Counter({(source, target): 2}),
        )[0]
    )
    assert "stale legacy budget" in checker.validate_import_budget(inventory, Counter())[0]
    inventory["legacy_imports"].append(record)
    assert any(
        "unique positive" in error
        for error in checker.validate_import_budget(
            inventory,
            Counter({(source, target): 1}),
        )
    )


def test_cli_fails_with_invalid_inventory_before_rendering(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/architecture-layers.json").write_text("[]")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(tmp_path), "--write"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "invalid inventory" in result.stdout
    assert not (tmp_path / "docs/architecture-layers-inventory.md").exists()


def test_legacy_module_cannot_add_a_new_pack_dependency(source_root):
    write_source(source_root, "import axis_verticals.logistics",
                 "services/api/src/axis_api/demo_reference.py")
    edges, errors, _ = checker.inspect_imports(source_root)
    assert errors == []
    assert checker.validate_import_budget({}, edges)


def test_directory_symlink_cannot_hide_unscanned_runtime_code(source_root, tmp_path):
    target = tmp_path / "external"
    target.mkdir()
    (target / "new.py").write_text("import axis_verticals.logistics")
    (source_root / "services/api/src/linked").symlink_to(target, target_is_directory=True)
    _, errors, _ = checker.inspect_imports(source_root)
    assert any("symlink" in error for error in errors)


def test_cli_detects_stale_render_and_write_cannot_approve_new_import(tmp_path, inventory):
    # A small real repository fixture exercises the CLI without loading Axis or GitHub.
    inventory["components"] = [
        item for item in inventory["components"] if item["kind"] in {"service", "package"}
    ]
    for item in inventory["components"]:
        folder = tmp_path / item["path"]
        folder.mkdir(parents=True)
        manifest = "package.json" if item["path"] in {"apps/web", "packages/schemas"} else (
            "pyproject.toml"
        )
        (folder / manifest).write_text("{}" if manifest.endswith("json") else "")
    for root in checker.CORE_ROOTS:
        (tmp_path / root).mkdir(parents=True)
    inventory["ports"] = [inventory["ports"][0]]
    inventory["ports"][0]["evidence"] = "contract.md"
    (tmp_path / "contract.md").write_text("Fixture contract")
    inventory["legacy_imports"] = []
    (tmp_path / "docs").mkdir()
    source = tmp_path / "docs/architecture-layers.json"
    source.write_text(json.dumps(inventory))
    original = source.read_bytes()
    command = [sys.executable, str(SCRIPT), "--repo-root", str(tmp_path)]
    assert subprocess.run([*command, "--write"], capture_output=True, check=False).returncode == 0
    generated = tmp_path / "docs/architecture-layers-inventory.md"
    generated.write_text("stale")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "inventory is stale" in result.stdout
    write_source(tmp_path, "import axis_verticals.logistics")
    result = subprocess.run([*command, "--write"], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "new core-to-vertical" in result.stdout
    assert source.read_bytes() == original
    assert generated.read_text() == "stale"


def test_owner_cannot_be_a_list_of_layers(inventory):
    inventory["components"][0]["owner"] = ["trust", "workflow"]
    assert any("exactly one valid owner" in error
               for error in checker.validate_inventory(inventory, REPO_ROOT))


def test_duplicate_json_ownership_keys_are_rejected(tmp_path):
    path = tmp_path / "inventory.json"
    path.write_text('{"component": {"owner":"trust","owner":"data"}}')
    with pytest.raises(ValueError, match="Duplicate JSON field"):
        checker.load_json(path)
