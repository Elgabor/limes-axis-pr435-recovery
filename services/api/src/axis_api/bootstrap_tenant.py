"""One-shot, out-of-band bootstrap for an empty production tenant registry."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from axis_api.config import Settings
from axis_api.db import create_session_factory, session_scope
from axis_api.persistence import AxisPersistenceRepository
from axis_api.platform_tenants import (
    REQUIRED_OPERATOR_SCOPE,
    REQUIRED_PROVISION_SCOPE,
    TenantBootstrapAdmin,
    TenantProvisionConflict,
    TenantProvisionRequest,
    bootstrap_first_tenant,
)

BOOTSTRAP_AUDIT_NOTE = "First tenant bootstrapped out of band with direct database authority."


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="axis-bootstrap-first-tenant",
        description=(
            "Provision exactly one tenant in an empty registry after database "
            "migrations. Exact replays are idempotent; later bootstraps are refused."
        ),
    )
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument(
        "--operator-id",
        required=True,
        help="Audited operator identity for this direct-database bootstrap.",
    )
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--bootstrap-admin-id")
    parser.add_argument("--bootstrap-admin-display-name")
    parser.add_argument(
        "--bootstrap-admin-scope",
        action="append",
        default=[],
        help="Requested IdP-owned scope to record as evidence; may be repeated.",
    )
    parser.add_argument("--note", action="append", default=[])
    return parser


def request_from_arguments(
    arguments: argparse.Namespace,
    *,
    parser: argparse.ArgumentParser,
) -> TenantProvisionRequest:
    admin_id = arguments.bootstrap_admin_id
    admin_name = arguments.bootstrap_admin_display_name
    if bool(admin_id) != bool(admin_name):
        parser.error(
            "--bootstrap-admin-id and --bootstrap-admin-display-name must be supplied together"
        )
    if arguments.bootstrap_admin_scope and not admin_id:
        parser.error("--bootstrap-admin-scope requires a bootstrap admin")

    bootstrap_admin = (
        TenantBootstrapAdmin(
            actor_id=admin_id,
            display_name=admin_name,
            scopes=arguments.bootstrap_admin_scope,
        )
        if admin_id and admin_name
        else None
    )
    return TenantProvisionRequest(
        tenant_id=arguments.tenant_id,
        display_name=arguments.display_name,
        description=arguments.description,
        requested_by=arguments.operator_id,
        # Direct database access is the out-of-band authority. These fixed
        # scopes reuse the same permission/audit path as API provisioning.
        actor_scopes=[REQUIRED_OPERATOR_SCOPE, REQUIRED_PROVISION_SCOPE],
        idempotency_key=arguments.idempotency_key,
        bootstrap_admin=bootstrap_admin,
        notes=[BOOTSTRAP_AUDIT_NOTE, *arguments.note],
    )


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
) -> int:
    parser = build_argument_parser()
    arguments = parser.parse_args(argv)
    try:
        request = request_from_arguments(arguments, parser=parser)
    except ValidationError as exc:
        print(f"First-tenant bootstrap input is invalid: {exc}", file=sys.stderr)
        return 2

    try:
        resolved_settings = settings or Settings()
    except ValidationError:
        # Pydantic's detailed settings error can echo environment values. Keep
        # operational diagnostics secret-safe and let the operator inspect the
        # deployment configuration through its normal secret-management path.
        print(
            "First-tenant bootstrap failed: runtime configuration is invalid.",
            file=sys.stderr,
        )
        return 1

    try:
        session_factory = create_session_factory(resolved_settings)
        with session_scope(session_factory) as session:
            result = bootstrap_first_tenant(
                AxisPersistenceRepository(session),
                request,
            )
    except TenantProvisionConflict as exc:
        print(f"First-tenant bootstrap refused: {exc.reason}.", file=sys.stderr)
        return 2
    except (NotImplementedError, SQLAlchemyError):
        print(
            "First-tenant bootstrap failed: the database is unavailable or migrations "
            "are incomplete.",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
    return 0


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
