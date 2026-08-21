from axis_sdk import _endpoints


def test_operational_endpoints_use_the_canonical_prefix() -> None:
    assert _endpoints.OPERATIONS_PREFIX == "/operations"
    assert _endpoints.DEMO_PREFIX == "/demo/manufacturing"
    assert _endpoints.list_approvals()[0].path == "/operations/approvals"
