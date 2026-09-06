from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def run_git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def exporter(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "prepare_oss_export", ROOT / "scripts/prepare_oss_export.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def source(tmp_path, exporter, monkeypatch):
    # The source policy rejects configured filters; fixture behavior must not
    # depend on a developer's global LFS/filter setup or the runner image.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = tmp_path / "source"
    repo.mkdir()
    run_git(repo, "init", "-q")
    run_git(repo, "config", "user.name", "Synthetic export test")
    run_git(repo, "config", "user.email", "fixture@example.invalid")
    run_git(repo, "config", "commit.gpgsign", "false")
    run_git(repo, "config", "core.hooksPath", "/dev/null")
    for area in (
        "apps/web",
        "services/api",
        "services/worker",
        "packages/schemas",
        "packages/sdk-python",
        "infra/docker",
        "infra/helm/limes-axis",
    ):
        (repo / area).mkdir(parents=True)
        (repo / area / "placeholder.txt").write_text("synthetic fixture\n")
    (repo / "scripts").mkdir()
    for script in ("prepare_oss_export.py", "check_edition_matrix.py"):
        (repo / "scripts" / script).write_bytes((ROOT / "scripts" / script).read_bytes())
    (repo / "docs").mkdir()
    (repo / "docs/topology.md").write_text("Synthetic topology\n")
    matrix = """schema_version = 1
last_reviewed = "2026-09-07"
decision_owner = "synthetic-fixture"
topology_adr = "docs/topology.md"

[[capabilities]]
id = "SDK"
name = "Synthetic SDK"
lifecycle = "current"
disposition = "shared-sdk"
areas = ["packages/sdk-python"]
evidence = ["docs/topology.md"]
rationale = "Synthetic exportable boundary"

[[capabilities]]
id = "CLOSED"
name = "Synthetic closed modules"
lifecycle = "current"
disposition = "hosted"
areas = ["apps/web", "services/api", "services/worker",
         "packages/schemas", "infra/docker", "infra/helm/limes-axis"]
evidence = ["docs/topology.md"]
rationale = "Synthetic non-exportable boundary"
"""
    (repo / exporter.MATRIX).write_text(matrix)
    # MIT family and notices are deliberately synthetic, not legal approval evidence.
    (repo / "LICENSE").write_text(
        "Permission is hereby granted, free of charge\nSynthetic fixture only\n"
    )
    (repo / "NOTICE").write_text("Copyright Synthetic Test Authors\n")
    code = "# SPDX-License-Identifier: MIT\nVALUE = 'synthetic'\n"
    (repo / "packages/sdk-python/client.py").write_text(code)
    policy = {
        "schema_version": 1,
        "commercial_version": "1.0.0",
        "oss_version": "0.1.0-test",
        "matrix_sha256": exporter.digest(matrix.encode()),
        "license": "MIT",
        "files": [
            {
                "path": path,
                "sha256": exporter.digest((repo / path).read_bytes()),
                "capabilities": [] if path in {"LICENSE", "NOTICE"} else ["SDK"],
                "spdx": "MIT",
                "attribution": "Copyright Synthetic Test Authors",
            }
            for path in ("LICENSE", "NOTICE", "packages/sdk-python/client.py")
        ],
    }
    (repo / "export-policy.json").write_bytes(exporter.canonical(policy))
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-qm", "Synthetic source fixture")
    return repo, policy


def save(source, exporter):
    repo, policy = source
    (repo / "export-policy.json").write_bytes(exporter.canonical(policy))
    run_git(repo, "add", ".")
    run_git(repo, "commit", "--allow-empty", "-qm", "Synthetic fixture revision")
    return run_git(repo, "rev-parse", "HEAD")


def prepare(source, exporter):
    repo, _ = source
    return exporter.prepare(repo, save(source, exporter), "export-policy.json")


def test_clean_checkouts_reproduce_identical_candidate_without_history(source, exporter, tmp_path):
    repo, _ = source
    commit = run_git(repo, "rev-parse", "HEAD")
    clone = tmp_path / "independent-checkout"
    subprocess.run(["git", "clone", "--no-local", "--quiet", str(repo), str(clone)], check=True)
    first, second = tmp_path / "candidate-a", tmp_path / "candidate-b"
    first_hash = exporter.build(repo, commit, "export-policy.json", first)
    assert first_hash == exporter.build(clone, commit, "export-policy.json", second)
    assert exporter.check(clone, commit, "export-policy.json", first) == first_hash
    assert not (first / "tree/.git").exists()
    assert not (first / "tree/services").exists()
    assert not (first / "tree/export-policy.json").exists()
    manifest = json.loads((first / "manifest.json").read_text())
    assert manifest["source_commit"] == commit
    assert manifest["release_status"] == "BLOCKED"
    assert "qualified-legal-review" in manifest["pending"]
    assert first_hash == hashlib.sha256((first / "manifest.json").read_bytes()).hexdigest()
    assert len(manifest["files"]) == 3


@pytest.mark.parametrize("mutation", ["untracked", "tracked", "staged", "wrong-head"])
def test_source_must_be_clean_at_exact_commit(source, exporter, mutation):
    repo, _ = source
    commit = run_git(repo, "rev-parse", "HEAD")
    if mutation == "untracked":
        (repo / "extra.txt").write_text("extra")
    elif mutation in {"tracked", "staged"}:
        (repo / "NOTICE").write_text("changed")
        if mutation == "staged":
            run_git(repo, "add", "NOTICE")
    else:
        commit = "0" * 40
    with pytest.raises(exporter.ExportError, match="clean|HEAD"):
        exporter.prepare(repo, commit, "export-policy.json")


@pytest.mark.parametrize(
    "path",
    [
        "../LICENSE",
        "/LICENSE",
        "a//b",
        "a/./b",
        "a/../b",
        ".git/config",
        ".env",
        "x/.git/objects/a",
        "a/*.py",
        "a\\b",
        "node_modules/a",
        "backup.zip",
        "a/secret.pem",
    ],
)
def test_nonportable_or_forbidden_paths_are_rejected(exporter, path):
    with pytest.raises(exporter.ExportError):
        exporter.safe_path(path)


@pytest.mark.parametrize(
    "mutation,match",
    [
        ("undecided", "undecided"),
        ("closed", "only current"),
        ("planned", "only current"),
        ("unknown", "unknown capability"),
        ("outside-area", "outside"),
        ("missing-mapping", "explicit capability"),
        ("stale-matrix", "matrix digest"),
        ("stale-file", "file digest"),
        ("duplicate", "duplicate"),
        ("wrong-spdx", "licensing"),
        ("missing-attribution", "attribution"),
        ("missing-notice", "mandatory"),
        ("extra-field", "invalid policy"),
    ],
)
def test_policy_failures_block_candidate(source, exporter, mutation, match):
    repo, policy = source
    entry = policy["files"][-1]
    matrix_path = repo / exporter.MATRIX
    if mutation in {"undecided", "planned"}:
        old, new = (
            ('disposition = "hosted"', 'disposition = "undecided"')
            if mutation == "undecided"
            else ('lifecycle = "current"', 'lifecycle = "planned"')
        )
        matrix_path.write_text(matrix_path.read_text().replace(old, new))
        policy["matrix_sha256"] = exporter.digest(matrix_path.read_bytes())
    elif mutation in {"closed", "unknown", "outside-area", "missing-mapping"}:
        entry["capabilities"] = {
            "closed": ["CLOSED"],
            "unknown": ["UNKNOWN"],
            "outside-area": ["SDK"],
            "missing-mapping": [],
        }[mutation]
        if mutation == "outside-area":
            entry["path"] = "services/api/placeholder.txt"
    elif mutation == "stale-matrix":
        policy["matrix_sha256"] = "0" * 64
    elif mutation == "stale-file":
        entry["sha256"] = "0" * 64
    elif mutation == "duplicate":
        policy["files"].append(dict(entry))
    elif mutation == "wrong-spdx":
        entry["spdx"] = "Apache-2.0"
    elif mutation == "missing-attribution":
        entry["attribution"] = ""
    elif mutation == "missing-notice":
        policy["files"] = [item for item in policy["files"] if item["path"] != "NOTICE"]
    else:
        policy["approval"] = True
    with pytest.raises(exporter.ExportError, match=match):
        prepare(source, exporter)


@pytest.mark.parametrize(
    "content,match",
    [
        (b"-----BEGIN PRIVATE KEY-----\nSYNTHETIC\n", "private-key"),
        (b"api_key = 'synthetic-not-a-real-credential'", "credential-assignment"),
        (b"INTERNAL-ONLY\n", "proprietary-marker"),
        (b"version https://git-lfs.github.com/spec/v1\n", "git-lfs-pointer"),
        (b"# SPDX-License-Identifier: Apache-2.0\n", "SPDX"),
        (b"binary\x00content", "binary"),
        (b"\xff", "binary"),
    ],
)
def test_scans_reject_synthetic_sensitive_and_unsupported_content(source, exporter, content, match):
    repo, policy = source
    entry = policy["files"][-1]
    (repo / entry["path"]).write_bytes(content)
    entry["sha256"] = exporter.digest(content)
    with pytest.raises(exporter.ExportError, match=match) as error:
        prepare(source, exporter)
    assert "synthetic-not-a-real-credential" not in str(error.value)


def test_symlink_source_is_never_followed(source, exporter):
    repo, policy = source
    path = repo / policy["files"][-1]["path"]
    path.unlink()
    path.symlink_to(repo / "NOTICE")
    with pytest.raises(exporter.ExportError, match="symlinks"):
        prepare(source, exporter)


@pytest.mark.parametrize(
    "mutation", ["bytes", "manifest", "extra", "missing", "symlink", "git-dir", "mode"]
)
def test_candidate_changes_fail_integrity_check(source, exporter, tmp_path, mutation):
    repo, _ = source
    commit = run_git(repo, "rev-parse", "HEAD")
    candidate = tmp_path / "candidate"
    exporter.build(repo, commit, "export-policy.json", candidate)
    if mutation == "bytes":
        (candidate / "tree/NOTICE").write_text("changed")
    elif mutation == "manifest":
        (candidate / "manifest.json").write_text("{}\n")
    elif mutation == "extra":
        (candidate / "tree/extra.txt").write_text("unexpected")
    elif mutation == "missing":
        (candidate / "tree/LICENSE").unlink()
    elif mutation == "symlink":
        (candidate / "tree/NOTICE").unlink()
        (candidate / "tree/NOTICE").symlink_to(repo / "NOTICE")
    elif mutation == "git-dir":
        (candidate / "tree/.git").mkdir()
    else:
        (candidate / "tree/NOTICE").chmod(0o777)
    with pytest.raises(exporter.ExportError):
        exporter.check(repo, commit, "export-policy.json", candidate)


def test_destination_is_exclusive_and_outside_source(source, exporter, tmp_path):
    repo, _ = source
    commit = run_git(repo, "rev-parse", "HEAD")
    with pytest.raises(exporter.ExportError, match="outside"):
        exporter.build(repo, commit, "export-policy.json", repo / "candidate")
    target = tmp_path / "existing"
    target.mkdir()
    sentinel = target / "keep"
    sentinel.write_text("preserve")
    with pytest.raises(exporter.ExportError, match="already exists"):
        exporter.build(repo, commit, "export-policy.json", target)
    assert sentinel.read_text() == "preserve"


def test_duplicate_json_fields_are_rejected(exporter):
    with pytest.raises(exporter.ExportError, match="duplicate JSON"):
        exporter.load_policy(b'{"schema_version":1,"schema_version":1}')


def test_cli_failure_does_not_echo_input_content(source, tmp_path):
    repo, _ = source
    commit = run_git(repo, "rev-parse", "HEAD")
    result = subprocess.run(
        [
            str(ROOT / "services/api/.venv/bin/python"),
            str(ROOT / "scripts/prepare_oss_export.py"),
            "build",
            "--repo-root",
            str(repo),
            "--commit",
            commit,
            "--policy",
            "../SYNTHETIC_SENSITIVE_VALUE",
            "--candidate",
            str(tmp_path / "candidate"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "SYNTHETIC_SENSITIVE_VALUE" not in result.stdout + result.stderr
    assert not (tmp_path / "candidate").exists()


@pytest.mark.parametrize("config_key", ["filter.fixture.clean", "remote.origin.promisor"])
def test_filters_and_partial_clones_are_rejected_before_status(source, exporter, config_key):
    repo, _ = source
    run_git(repo, "config", config_key, "true")
    with pytest.raises(exporter.ExportError, match="full checkout without configured Git filters"):
        exporter.prepare(repo, run_git(repo, "rev-parse", "HEAD"), "export-policy.json")


def test_generator_must_match_pinned_source(source, exporter):
    repo, _ = source
    script = repo / "scripts/prepare_oss_export.py"
    script.write_text(script.read_text() + "\n# Different synthetic generator revision\n")
    with pytest.raises(exporter.ExportError, match="generator must match"):
        prepare(source, exporter)


@pytest.mark.parametrize(
    "mutation,match",
    [
        ("license-text", "license family"),
        ("notice", "retain every"),
        ("large-file", "2 MiB"),
        ("case-collision", "case-colliding"),
    ],
)
def test_legal_inventory_and_size_boundaries(source, exporter, mutation, match):
    repo, policy = source
    if mutation == "case-collision":
        policy["files"].append({**policy["files"][-1], "path": "packages/sdk-python/CLIENT.py"})
    else:
        entry = policy["files"][
            -1 if mutation == "large-file" else (0 if mutation == "license-text" else 1)
        ]
        data = b"x" * (exporter.MAX_FILE_BYTES + 1) if mutation == "large-file" else b"changed\n"
        (repo / entry["path"]).write_bytes(data)
        entry["sha256"] = exporter.digest(data)
    with pytest.raises(exporter.ExportError, match=match):
        prepare(source, exporter)
