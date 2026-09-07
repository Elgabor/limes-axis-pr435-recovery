"""Offline ownership inventory and core-to-vertical import ratchet; never imports app code."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

LAYERS = {
    "deployment",
    "trust",
    "data",
    "operational-model",
    "workflow",
    "intelligence",
    "experience",
}
CORE_ROOTS = (
    "services/api/src",
    "services/worker/src",
    "packages/sdk-python/src",
)
LEGACY_MODULES = frozenset(
    {
        "axis_api.demo",
        "axis_api.demo_bootstrap",
        "axis_api.demo_reference",
        "axis_api.manufacturing_metadata",
        "axis_api.manufacturing_empty",
        "axis_api.manufacturing_operations",
        "axis_api.action_reference",
        "axis_api.agent_reference",
        "axis_api.approval_reference",
        "axis_api.audit_reference",
        "axis_api.connector_reference",
        "axis_api.model_routing_reference",
        "axis_api.ontology_reference",
        "axis_api.workflow_reference",
    }
)


def is_vertical(target: str) -> bool:
    return any(
        target == module or target.startswith(module + ".") for module in LEGACY_MODULES
    ) or any(
        part in {"axis_verticals", "axis_packs", "verticals", "packs"}
        or part.startswith("manufacturing_")
        for part in target.split(".")
    )


def inspect_imports(repo_root: Path) -> tuple[Counter, list[str], int]:
    edges: Counter = Counter()
    errors: list[str] = []
    count = 0
    root_names = set(CORE_ROOTS) | {
        path.relative_to(repo_root).as_posix()
        for pattern in ("services/*/src", "packages/*/src")
        for path in repo_root.glob(pattern)
        if path.is_dir()
    }
    for root_name in sorted(root_names):
        root = repo_root / root_name
        if not root.is_dir() or root.is_symlink() or not root.resolve().is_relative_to(repo_root):
            errors.append(f"missing core source root: {root_name}")
            continue
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(repo_root).as_posix()
            if path.is_symlink():
                errors.append(f"core source symlink is not supported: {relative}")
                continue
            if not path.is_file() or path.suffix != ".py":
                continue
            module = ".".join(path.relative_to(root).with_suffix("").parts)
            package = (
                module.removesuffix(".__init__")
                if path.stem == "__init__"
                else (module.rpartition(".")[0])
            )
            if is_vertical(module) and module not in LEGACY_MODULES:
                errors.append(f"new vertical module inside shared core: {relative}")
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
            except (SyntaxError, UnicodeError) as error:
                errors.append(f"cannot parse core source: {relative}: {type(error).__name__}")
                continue
            count += 1
            # Historical vertical modules can depend on their own reference types.
            # Shared core importers have only the exact reviewed legacy budget below.
            for node in ast.walk(tree):
                targets: list[str] = []
                if isinstance(node, ast.Import):
                    targets = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    base = node.module or ""
                    if node.level:
                        try:
                            base = importlib.util.resolve_name("." * node.level + base, package)
                        except (ImportError, ValueError):
                            errors.append(f"invalid relative import: {relative}:{node.lineno}")
                            continue
                    targets = [base + "." + alias.name for alias in node.names]
                for target in targets:
                    legacy_target = any(
                        target == old or target.startswith(old + ".") for old in LEGACY_MODULES
                    )
                    if is_vertical(target) and (module not in LEGACY_MODULES or not legacy_target):
                        edges[(relative, target)] += 1
                # No dynamic import machinery exists in these roots today. Do not
                # let a future loader bypass the static boundary silently.
                if any(
                    t == "importlib" or t.startswith("importlib.") or t == "builtins.__import__"
                    for t in targets
                ):
                    errors.append(f"dynamic loading needs architecture review: {relative}")
                if isinstance(node, ast.Call) and (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "__import__"
                    or isinstance(node.func, ast.Attribute)
                    and node.func.attr == "__import__"
                ):
                    errors.append(f"dynamic loading needs architecture review: {relative}")
    return edges, errors, count


def validate_inventory(
    inventory: dict, repo_root: Path, live_issues: list | None = None
) -> list[str]:
    errors: list[str] = []
    if type(inventory.get("schema_version")) is not int or inventory["schema_version"] != 1:
        errors.append("schema_version must be 1")
    revision = inventory.get("source_revision")
    if not isinstance(revision, str) or re.fullmatch(r"[a-f0-9]{40}", revision) is None:
        errors.append("source_revision must identify the reviewed baseline commit")
    if not isinstance(inventory.get("decision_owner"), str) or not inventory["decision_owner"]:
        errors.append("decision_owner is required")
    if set(inventory.get("layers", {})) != LAYERS:
        errors.append("inventory must define exactly the seven architecture layers")
    for layer, record in inventory.get("layers", {}).items():
        for key in ("responsibility", "failure", "tenancy", "deployment", "contract"):
            if not isinstance(record.get(key), str) or not record[key].strip():
                errors.append(f"layer {layer}: missing {key}")
    ids: set[str] = set()
    paths: set[str] = set()
    service_paths: set[str] = set()
    for component in inventory.get("components", []):
        identifier = component.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            errors.append("component ids must be unique nonempty strings")
        else:
            ids.add(identifier)
        validate_owner(component, f"component {identifier}", errors)
        if component.get("kind") not in {"service", "package", "module", "delivery"}:
            errors.append(f"component {identifier}: invalid kind")
        path = component.get("path", "")
        target = (repo_root / path).resolve()
        if not path or path in paths or not target.is_relative_to(repo_root) or not target.exists():
            errors.append(f"component {identifier}: path must exist once inside repository")
        paths.add(path)
        if component.get("kind") in {"service", "package"}:
            service_paths.add(path)
    discovered = {
        path.parent.relative_to(repo_root).as_posix()
        for area in ("apps", "services", "packages")
        for manifest in ("package.json", "pyproject.toml")
        for path in repo_root.glob(f"{area}/*/{manifest}")
    }
    if discovered != service_paths:
        errors.append("service/package inventory differs from repository manifests")
    numbers: set[int] = set()
    for issue in inventory.get("issues", []):
        number = issue.get("number")
        if type(number) is not int or number < 1 or number in numbers:
            errors.append("issue numbers must be unique positive integers")
        else:
            numbers.add(number)
        validate_owner(issue, f"issue {number}", errors)
        if not issue.get("title"):
            errors.append(f"issue {number}: missing title")
    snapshot = inventory.get("open_issue_snapshot", {})
    try:
        date.fromisoformat(snapshot.get("captured_at", ""))
    except (TypeError, ValueError):
        errors.append("issue snapshot requires a YYYY-MM-DD date")
    if snapshot.get("repository") != "Limes-Labs/limes-axis":
        errors.append("issue snapshot must identify this repository")
    snapshot_numbers = snapshot.get("numbers", [])
    if (
        not snapshot_numbers
        or set(snapshot_numbers) != numbers
        or len(snapshot_numbers) != len(numbers)
    ):
        errors.append("issue ownership must cover the complete recorded open-issue snapshot once")
    if live_issues is not None:
        missing = {issue["number"] for issue in live_issues} - numbers
        if missing:
            errors.append(f"unmapped currently open issues: {sorted(missing)}")
    if not inventory.get("ports"):
        errors.append("public ports must be inventoried")
    port_ids: set[str] = set()
    for port in inventory.get("ports", []):
        identifier = port.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in port_ids:
            errors.append("port ids must be unique")
        else:
            port_ids.add(identifier)
        if port.get("owner") not in LAYERS or port.get("status") not in {"current", "planned"}:
            errors.append(f"port {identifier}: invalid owner/status")
        for key in ("input", "output", "failure", "compatibility", "evidence"):
            if not isinstance(port.get(key), str) or not port[key].strip():
                errors.append(f"port {identifier}: missing {key}")
        evidence = (repo_root / port.get("evidence", "")).resolve()
        if not evidence.is_relative_to(repo_root) or not evidence.is_file():
            errors.append(f"port {identifier}: evidence must be a repository file")
    return errors


def validate_owner(record: dict, label: str, errors: list[str]) -> None:
    owner = record.get("owner")
    dependencies = record.get("dependencies")
    if not isinstance(owner, str) or owner not in LAYERS:
        errors.append(f"{label}: exactly one valid owner is required")
    if not isinstance(dependencies, list) or any(
        not isinstance(dep, str) or dep not in LAYERS for dep in dependencies
    ):
        errors.append(f"{label}: dependencies must name layers")
    elif len(dependencies) != len(set(dependencies)) or owner in dependencies:
        errors.append(f"{label}: duplicate or self dependency")


def validate_import_budget(inventory: dict, edges: Counter) -> list[str]:
    errors: list[str] = []
    budget: Counter = Counter()
    for record in inventory.get("legacy_imports", []):
        for target, count in record.get("targets", {}).items():
            key = (record.get("source"), target)
            if key in budget or type(count) is not int or count < 1 or not is_vertical(target):
                errors.append("legacy imports require unique positive exact edge counts")
            budget[key] = count
    for key in sorted(edges.keys() | budget.keys()):
        if edges[key] > budget[key]:
            errors.append(f"new core-to-vertical import: {key[0]} -> {key[1]}")
        elif edges[key] < budget[key]:
            errors.append(f"stale legacy budget, remove reduced edge: {key[0]} -> {key[1]}")
    return errors


def render_inventory(inventory: dict) -> str:
    lines = [
        "# Axis layer ownership inventory",
        "",
        "<!-- Generated by scripts/check_architecture_layers.py; "
        "edit architecture-layers.json. -->",
        "",
        f"Snapshot: {inventory['open_issue_snapshot']['captured_at']}.",
        "",
        "Each component and issue has one accountable layer. Dependencies are required",
        "collaborations, not permission to import a vertical into shared core.",
        "",
        "## Components",
        "",
        "| Component | Owner | Dependencies | Evidence path |",
        "| --- | --- | --- | --- |",
    ]
    for item in inventory["components"]:
        lines.append(
            f"| {item['id']} | {item['owner']} | {', '.join(item['dependencies']) or 'None'} "
            f"| [`{item['path']}`](../{item['path']}) |"
        )
    lines += [
        "",
        "## Issue snapshot",
        "",
        "Closed issues may retain ownership after this snapshot.",
        "New open issues need an explicit assignment at the next review.",
        "",
        "| Issue | Owner | Dependencies |",
        "| --- | --- | --- |",
    ]
    for item in inventory["issues"]:
        title = item["title"].replace("|", "\\|")
        lines.append(
            f"| [#{item['number']}](https://github.com/Limes-Labs/limes-axis/issues/"
            f"{item['number']}) {title} | {item['owner']} "
            f"| {', '.join(item['dependencies']) or 'None'} |"
        )
    lines += [
        "",
        "## Existing core-to-reference import debt",
        "",
        "These exact legacy edges are retained for compatibility, not approved for growth.",
        "Remove budget entries when an edge disappears. No automatic baseline refresh exists.",
        "",
        "| Shared core file | Imported legacy symbols (occurrences) |",
        "| --- | --- |",
    ]
    for item in inventory["legacy_imports"]:
        symbols = "<br>".join(f"`{key}` ({value})" for key, value in item["targets"].items())
        lines.append(f"| [`{item['source']}`](../{item['source']}) | {symbols} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--issues-snapshot", type=Path, help="Optional fresh gh issue-list JSON")
    parser.add_argument(
        "--write", action="store_true", help="Render documentation; never reset debt"
    )
    args = parser.parse_args()
    root = args.repo_root.resolve()
    try:
        inventory = load_json(root / "docs/architecture-layers.json")
        live = load_json(args.issues_snapshot) if args.issues_snapshot else None
        errors = validate_inventory(inventory, root, live)
        edges, import_errors, count = inspect_imports(root)
        errors += import_errors + validate_import_budget(inventory, edges)
        if errors:
            for error in errors:
                print(f"architecture: {error}")
            return 1
        rendered = render_inventory(inventory)
        target = root / "docs/architecture-layers-inventory.md"
        if args.write:
            target.write_text(rendered, encoding="utf-8")
        elif not target.is_file() or target.read_text(encoding="utf-8") != rendered:
            print("architecture: inventory is stale; run with --write")
            return 1
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"architecture: invalid inventory or source: {type(error).__name__}")
        return 1
    print(
        f"Architecture layers OK ({len(inventory['components'])} components, "
        f"{len(inventory['issues'])} issues, {count} Python files, "
        f"{sum(edges.values())} existing legacy imports; zero new imports)"
    )
    return 0


def load_json(path: Path):
    def unique_fields(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError("Duplicate JSON field")
            result[name] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_fields)


if __name__ == "__main__":
    raise SystemExit(main())
