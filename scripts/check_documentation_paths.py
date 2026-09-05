from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote

INLINE_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\n]+)\)")
REFERENCE_LINK = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)", re.MULTILINE)
EXCLUDED_PARTS = {
    ".audit",
    ".axis",
    ".git",
    ".next",
    ".pnpm-store",
    ".pytest_cache",
    ".venv",
    ".worktrees",
    "node_modules",
}
EXTERNAL_SCHEMES = ("data:", "http:", "https:", "mailto:", "tel:")


class BrokenReference(NamedTuple):
    document: Path
    line: int
    target: str


def markdown_documents(repo_root: Path) -> list[Path]:
    documents: list[Path] = []
    for directory, subdirectories, files in os.walk(repo_root):
        subdirectories[:] = [name for name in subdirectories if name not in EXCLUDED_PARTS]
        documents.extend(Path(directory) / name for name in files if name.endswith(".md"))
    return sorted(documents)


def normalize_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<"):
        closing = target.find(">")
        if closing != -1:
            return target[1:closing]
    return target.split(maxsplit=1)[0]


def local_targets(text: str) -> list[tuple[int, str]]:
    matches = [*INLINE_LINK.finditer(text), *REFERENCE_LINK.finditer(text)]
    return [
        (text.count("\n", 0, match.start()) + 1, normalize_target(match.group(1)))
        for match in sorted(matches, key=lambda item: item.start())
    ]


def broken_references(
    repo_root: Path, documents: list[Path] | None = None,
) -> list[BrokenReference]:
    broken: list[BrokenReference] = []
    for document in markdown_documents(repo_root) if documents is None else documents:
        text = document.read_text(encoding="utf-8")
        for line, target in local_targets(text):
            lowered = target.lower()
            if not target or target.startswith("#") or lowered.startswith(EXTERNAL_SCHEMES):
                continue
            path_text = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not path_text:
                continue
            candidate = (
                repo_root / path_text.removeprefix("/")
                if path_text.startswith("/")
                else document.parent / path_text
            ).resolve()
            if not candidate.is_relative_to(repo_root) or not candidate.exists():
                broken.append(
                    BrokenReference(
                        document=document.relative_to(repo_root),
                        line=line,
                        target=target,
                    )
                )
    return broken


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate repository-local Markdown paths.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    documents = markdown_documents(repo_root)
    broken = broken_references(repo_root, documents)
    if broken:
        for reference in broken:
            print(f"{reference.document}:{reference.line}: missing path: {reference.target}")
        return 1
    print(f"Documentation paths OK ({len(documents)} files checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
