"""Prepare an internal files-only candidate. This tool never authorizes publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from check_edition_matrix import export_blockers, validate_matrix

MATRIX = "docs/edition-capabilities.toml"
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_FILES = 1000
LICENSE_MARKERS = {
    "Apache-2.0": "Apache License",
    "MIT": "Permission is hereby granted, free of charge",
    "BSD-3-Clause": "Neither the name of the copyright holder",
}
PATTERNS = {
    "private-key": re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    "credential-token": re.compile(
        r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
        r"AKIA[A-Z0-9]{16}|sk-(?:proj-)?[A-Za-z0-9_-]{24,})"
    ),
    "credential-assignment": re.compile(
        r"(?i)(?:password|api[_-]?key|access[_-]?token|client[_-]?secret)"
        r"\s*[:=]\s*[\"']?[^\s\"'<>${}]{12,}"
    ),
    "proprietary-marker": re.compile(
        r"(?i)\b(?:confidential|proprietary|internal[- ]only|not for redistribution)\b"
    ),
    "git-lfs-pointer": re.compile(r"version https://git-lfs.github.com/spec/"),
}


class ExportError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ExportError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def git(repo: Path, *args: str, allow_no_match: bool = False) -> bytes:
    result = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(repo),
            *args,
        ],
        capture_output=True,
        check=False,
    )
    require(
        result.returncode == 0 or (allow_no_match and result.returncode == 1 and not result.stdout),
        "source Git command failed (output withheld)",
    )
    return result.stdout


def safe_path(value: Any) -> str:
    require(isinstance(value, str), "path must be a string")
    require(
        re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", value) is not None,
        "path must be an exact portable relative path",
    )
    parts = value.lower().split("/")
    require(
        not any(
            part.startswith(".")
            or part
            in {
                "node_modules",
                "__pycache__",
                "test-results",
                "playwright-report",
                "dist",
                "build",
                "coverage",
                "artifacts",
                "backups",
                "customer-data",
            }
            for part in parts
        ),
        "hidden, runtime or generated path is forbidden",
    )
    require(
        not value.lower().endswith((".pem", ".key", ".p12", ".db", ".sqlite", ".zip")),
        "credential, database or archive path is forbidden",
    )
    return value


def exact_keys(value: Any, keys: set[str], label: str) -> None:
    require(isinstance(value, dict) and set(value) == keys, f"invalid {label} fields")


def load_policy(data: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result

    policy = json.loads(data, object_pairs_hook=unique)
    exact_keys(
        policy,
        {
            "schema_version",
            "commercial_version",
            "oss_version",
            "matrix_sha256",
            "license",
            "files",
        },
        "policy",
    )
    require(
        type(policy["schema_version"]) is int and policy["schema_version"] == 1,
        "unsupported policy schema",
    )
    for field in ("commercial_version", "oss_version"):
        require(
            isinstance(policy[field], str)
            and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", policy[field])
            is not None,
            "edition versions must be explicit semantic versions",
        )
    require(
        isinstance(policy["license"], str) and policy["license"] in LICENSE_MARKERS,
        "license requires a supported explicit policy",
    )
    require(
        isinstance(policy["files"], list) and 2 <= len(policy["files"]) <= MAX_FILES,
        "policy requires 2..1000 exact files including LICENSE and NOTICE",
    )
    return policy


def prepare(repo: Path, commit: str, policy_path: str) -> dict[str, tuple[bytes, int]]:
    repo = repo.resolve()
    require(
        not git(
            repo,
            "config",
            "--get-regexp",
            r"^filter\.|^extensions\.partialclone$|^remote\..*\.promisor$",
            allow_no_match=True,
        ),
        "source requires a full checkout without configured Git filters",
    )
    require(
        re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit) is not None,
        "commit must be a full immutable object ID",
    )
    require(
        git(repo, "rev-parse", "--show-toplevel").decode().strip() == str(repo),
        "source must be the checkout root",
    )
    require(
        git(repo, "rev-parse", "HEAD").decode().strip() == commit,
        "checkout HEAD differs from requested commit",
    )
    require(
        not git(repo, "status", "--porcelain", "--untracked-files=all"),
        "source checkout must be clean",
    )
    inventory: dict[str, tuple[str, str, str]] = {}
    for record in git(repo, "ls-tree", "-rz", "--full-tree", commit).split(b"\0"):
        if record:
            meta, path = record.split(b"\t", 1)
            mode, kind, oid = meta.decode("ascii").split()
            inventory[path.decode("utf-8")] = (mode, kind, oid)

    def blob(path: str) -> tuple[bytes, int]:
        require(path in inventory, "allowlisted input is not a committed file")
        mode, kind, oid = inventory[path]
        require(
            kind == "blob" and mode in {"100644", "100755"},
            "symlinks, submodules and special files are forbidden",
        )
        size = int(git(repo, "cat-file", "-s", oid))
        require(size <= MAX_FILE_BYTES, "file exceeds 2 MiB candidate limit")
        return git(repo, "cat-file", "blob", oid), int(mode[-3:], 8)

    for script in ("prepare_oss_export.py", "check_edition_matrix.py"):
        script_data, _ = blob("scripts/" + script)
        require(
            script_data == Path(__file__).with_name(script).read_bytes(),
            "generator must match the pinned source revision",
        )

    policy_path = safe_path(policy_path)
    policy_data, _ = blob(policy_path)
    policy = load_policy(policy_data)
    matrix_data, _ = blob(MATRIX)
    require(digest(matrix_data) == policy["matrix_sha256"], "matrix digest changed")
    matrix = tomllib.loads(matrix_data.decode("utf-8"))
    require(not validate_matrix(matrix, repo), "edition matrix is invalid")
    require(not export_blockers(matrix), "undecided capability blocks every export")
    capabilities = {entry["id"]: entry for entry in matrix["capabilities"]}
    output: dict[str, tuple[bytes, int]] = {}
    manifest_files = []
    seen: set[str] = set()
    total_bytes = 0
    for entry in policy["files"]:
        exact_keys(entry, {"path", "sha256", "capabilities", "spdx", "attribution"}, "file")
        path = safe_path(entry["path"])
        require(path.casefold() not in seen, "duplicate or case-colliding path")
        require(
            not any(
                path.casefold().startswith(other + "/") or other.startswith(path.casefold() + "/")
                for other in seen
            ),
            "file and directory paths collide",
        )
        seen.add(path.casefold())
        require(
            path not in {policy_path, MATRIX},
            "private export control files are forbidden",
        )
        ids = entry["capabilities"]
        require(
            isinstance(ids, list) and all(isinstance(item, str) for item in ids),
            "capabilities must be a string array",
        )
        require(len(set(ids)) == len(ids), "duplicate capability assignment")
        if path in {"LICENSE", "NOTICE"}:
            require(not ids, "legal root files must have empty capabilities")
        else:
            require(bool(ids), "source file needs an explicit capability assignment")
            for capability_id in ids:
                require(capability_id in capabilities, "unknown capability assignment")
                capability = capabilities[capability_id]
                require(
                    capability["disposition"] in {"oss", "shared-sdk"}
                    and capability["lifecycle"] == "current",
                    "only current OSS or shared-SDK capabilities can be staged",
                )
                require(
                    any(
                        path == area or path.startswith(area + "/") for area in capability["areas"]
                    ),
                    "file lies outside its assigned capability areas",
                )
        require(
            entry["spdx"] == policy["license"],
            "mixed or unknown licensing requires a reviewed policy extension",
        )
        require(
            isinstance(entry["attribution"], str) and 1 <= len(entry["attribution"].strip()) <= 500,
            "every file needs explicit attribution",
        )
        data, mode = blob(path)
        total_bytes += len(data)
        require(total_bytes <= MAX_TOTAL_BYTES, "candidate exceeds 20 MiB limit")
        require(digest(data) == entry["sha256"], "allowlisted file digest changed")
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ExportError("binary content requires a reviewed policy extension") from exc
        require(
            not any(ord(char) < 32 and char not in "\t\n\r" for char in content),
            "binary or control content is forbidden",
        )
        for rule, pattern in PATTERNS.items():
            require(
                pattern.search(content) is None,
                f"content scan failed: {rule} (match withheld)",
            )
        for identifier in re.findall(r"SPDX-License-Identifier:\s*([^\r\n]+)", content):
            require(
                identifier.strip() == entry["spdx"],
                "SPDX declaration disagrees with policy",
            )
        output["tree/" + path] = (data, mode)
        manifest_files.append(
            {
                **entry,
                "capabilities": sorted(ids),
                "mode": f"{mode:03o}",
                "size_bytes": len(data),
            }
        )
    require(
        "tree/LICENSE" in output and "tree/NOTICE" in output,
        "LICENSE and NOTICE are mandatory allowlisted files",
    )
    require(
        LICENSE_MARKERS[policy["license"]] in output["tree/LICENSE"][0].decode(),
        "LICENSE does not match the declared license family",
    )
    notice = output["tree/NOTICE"][0].decode()
    require(
        all(entry["attribution"] in notice for entry in manifest_files),
        "NOTICE must retain every declared attribution",
    )
    manifest = {
        "schema_version": 1,
        "source_commit": commit,
        "commercial_version": policy["commercial_version"],
        "oss_version": policy["oss_version"],
        "matrix_sha256": digest(matrix_data),
        "policy_sha256": digest(policy_data),
        "generator_sha256": digest(Path(__file__).read_bytes()),
        "matrix_checker_sha256": digest(
            Path(__file__).with_name("check_edition_matrix.py").read_bytes()
        ),
        "license": policy["license"],
        "files": sorted(manifest_files, key=lambda entry: entry["path"]),
        "checks": [
            "exact-allowlist",
            "committed-blobs-only",
            "matrix-disposition",
            "file-digests",
            "bounded-text-scan-v1",
            "license-family",
            "spdx",
            "attribution",
        ],
        "release_status": "BLOCKED",
        "pending": [
            "independent-offline-secret-and-proprietary-scan",
            "dependency-provenance",
            "useful-edition-build-and-contract-tests",
            "independent-reproduction",
            "commercial-release-owner-approval",
            "security-reviewer-approval",
            "product-owner-approval",
            "qualified-legal-review",
            "fresh-history-release-review",
        ],
    }
    manifest_data = canonical(manifest)
    output["manifest.json"] = (manifest_data, 0o644)
    output["manifest.sha256"] = (
        (digest(manifest_data) + "  manifest.json\n").encode(),
        0o644,
    )
    return output


def destination(repo: Path, path: Path) -> Path:
    require(not path.is_symlink(), "destination must not be a symlink")
    resolved = path.resolve()
    require(
        not resolved.is_relative_to(repo.resolve()),
        "candidate must be outside the source checkout",
    )
    require(
        not any(part.startswith(".") for part in resolved.parts if part != "/"),
        "candidate must not be inside a hidden or Git directory",
    )
    common = Path(
        git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip()
    )
    require(
        not resolved.is_relative_to(common.resolve()),
        "candidate must be outside Git storage",
    )
    require(resolved.parent.is_dir(), "candidate parent must already exist")
    return resolved


def build(repo: Path, commit: str, policy: str, target: Path) -> str:
    target = destination(repo, target)
    require(not target.exists(), "candidate destination already exists")
    expected = prepare(repo, commit, policy)
    target.mkdir(mode=0o700)  # Exclusive creation; never overwrite or remove an existing tree.
    for relative, (data, mode) in expected.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
        path.chmod(mode)
    return digest(expected["manifest.json"][0])


def check(repo: Path, commit: str, policy: str, target: Path) -> str:
    target = destination(repo, target)
    require(target.is_dir(), "candidate directory is missing")
    expected = prepare(repo, commit, policy)
    files: set[str] = set()
    directories: set[str] = set()
    expected_directories = {
        str(parent)
        for relative in expected
        for parent in Path(relative).parents
        if str(parent) != "."
    }
    for root, dirs, names in os.walk(target, followlinks=False):
        for name in [*dirs, *names]:
            path = Path(root) / name
            require(not path.is_symlink(), "candidate contains a symlink")
            relative = path.relative_to(target).as_posix()
            if name in dirs:
                directories.add(relative)
                continue
            require(
                path.is_file() and relative in expected,
                "candidate has an unexpected file",
            )
            data, mode = expected[relative]
            require(
                path.stat().st_size == len(data) and path.read_bytes() == data,
                "candidate bytes differ from the pinned source or manifest",
            )
            require(
                path.stat().st_mode & 0o7777 == mode,
                "candidate file permissions changed",
            )
            files.add(relative)
    require(
        files == set(expected) and directories == expected_directories,
        "candidate has missing files or unexpected directories",
    )
    return digest(expected["manifest.json"][0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("build", "check"))
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument(
        "--policy", required=True, help="Committed repository-relative JSON allowlist"
    )
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = (build if args.operation == "build" else check)(
            args.repo_root, args.commit, args.policy, args.candidate
        )
    except (
        ExportError,
        OSError,
        TypeError,
        KeyError,
        UnicodeError,
        json.JSONDecodeError,
        tomllib.TOMLDecodeError,
    ) as exc:
        # Do not echo Git output, file contents, credentials or malformed input values.
        print(f"OSS candidate FAIL: {exc if isinstance(exc, ExportError) else type(exc).__name__}")
        return 1
    print(f"OSS candidate PASS; manifest sha256={result}; publication BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
