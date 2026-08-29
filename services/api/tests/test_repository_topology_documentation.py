from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ADR = REPO_ROOT / "docs/adr/0002-commercial-source-and-oss-export-boundary.md"


def test_repository_topology_adr_records_fail_closed_export_contract() -> None:
    decision = " ".join(ADR.read_text(encoding="utf-8").split())

    required_contract = (
        "**Status:** Accepted",
        "complete commercial source of truth",
        "fresh initial history",
        "One-way publication flow",
        "Release ownership",
        "Versioning and compatibility",
        "Disclosure threat model",
        "allowlist",
        "`undecided` fails closed",
        "qualified legal review",
        "`NOT RUN`",
    )
    missing = [item for item in required_contract if item not in decision]

    assert missing == [], f"repository topology ADR is missing: {missing}"


def test_current_architecture_and_readme_link_to_topology_decision() -> None:
    expected_link = "adr/0002-commercial-source-and-oss-export-boundary.md"
    documents = (
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs/architecture.md",
    )

    missing = [
        str(document.relative_to(REPO_ROOT))
        for document in documents
        if expected_link not in document.read_text(encoding="utf-8")
    ]

    assert missing == [], f"current topology is not linked from: {missing}"


def test_superseded_public_upstream_topology_is_not_current_policy() -> None:
    current_policy_documents = (
        REPO_ROOT / "README.md",
        REPO_ROOT / "plan.md",
        REPO_ROOT / "SECURITY.md",
        REPO_ROOT / "SUPPORT.md",
        REPO_ROOT / "CONTRIBUTING.md",
        REPO_ROOT / "docs/architecture.md",
        REPO_ROOT / "docs/threat-model.md",
        REPO_ROOT / "docs/plans/2026-07-11-operate-milestone.md",
    )
    forbidden = (
        "private downstream",
        "core development remains public-upstream",
        "The public repo is used",
    )
    stale = [
        f"{document.relative_to(REPO_ROOT)}: {phrase}"
        for document in current_policy_documents
        for phrase in forbidden
        if phrase in document.read_text(encoding="utf-8")
    ]

    assert stale == [], f"superseded repository topology remains: {stale}"
