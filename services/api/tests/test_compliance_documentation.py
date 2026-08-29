from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MATRIX = REPO_ROOT / "docs/compliance-applicability-and-evidence.md"


def matrix_text() -> str:
    return " ".join(MATRIX.read_text(encoding="utf-8").split())


def test_compliance_matrix_covers_frameworks_roles_and_controls() -> None:
    text = matrix_text()
    required = (
        "ISO/IEC 27001",
        "GDPR",
        "EU AI Act",
        "NIS2",
        "Roles By Deployment",
        "Limes Hosted multi-tenant",
        "Customer private cloud or on-prem",
        "Future OSS self-hosting",
        "`GOV-01`",
        "`IAM-01`",
        "`DAT-01`",
        "`SUP-01`",
        "`SEC-01`",
        "`LOG-01`",
        "`INC-01`",
        "`BCM-01`",
        "`AI-01`",
        "`AI-02`",
        "`ASS-01`",
    )

    missing = [item for item in required if item not in text]

    assert missing == [], f"compliance scope is missing: {missing}"


def test_compliance_matrix_assigns_evidence_owners_cadence_and_gaps() -> None:
    text = matrix_text()
    required = (
        "Repository Evidence Register",
        "External Evidence Required",
        "Customer-Dependent Control Allocation",
        "Owner and minimum cadence",
        "`O-ISMS`",
        "`O-PRIV`",
        "`O-AI`",
        "`O-NIS`",
        "`O-CUST`",
        "`GAP-ISO-01`",
        "`GAP-GDPR-01`",
        "`GAP-AI-01`",
        "`GAP-NIS-01`",
        "No compliance risk is currently recorded as accepted",
    )

    missing = [item for item in required if item not in text]

    assert missing == [], f"compliance evidence governance is missing: {missing}"


def test_compliance_matrix_keeps_external_reviews_and_claims_fail_closed() -> None:
    text = matrix_text()

    assert "qualified counsel" in text
    assert "qualified certification specialist" in text
    assert "`NOT RUN`" in text
    assert "do not claim" in text
    assert "It is not legal advice" in text
    assert "A product control is only one possible evidence item" in text
