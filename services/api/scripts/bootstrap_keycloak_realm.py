"""Operator CLI: check or converge a Keycloak realm into Axis-ready shape.

Check mode (default) is a read-only dry run; apply mode converges the realm.
Credentials come from the environment, never from argv, and diagnostics never
include tokens, client secrets, passwords, or raw IdP responses.

Example:

    export AXIS_IDP_ADMIN_USERNAME=axis-bootstrap
    export AXIS_IDP_ADMIN_PASSWORD=...  # from your secret store
    python scripts/bootstrap_keycloak_realm.py \
        --base-url https://keycloak.example.internal \
        --realm axis \
        --client-id limes-axis-web \
        --redirect-uri https://axis.example.com/api/identity/oidc/callback \
        --web-origin https://axis.example.com \
        --post-logout-uri https://axis.example.com/ \
        --mode check
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence

from axis_api.idp_bootstrap import (
    AxisIdpClientSpec,
    AxisRealmSpec,
    KeycloakBootstrapUnavailable,
    UrllibKeycloakAdminHttp,
    apply_realm,
    check_realm,
)

ADMIN_USERNAME_ENV = "AXIS_IDP_ADMIN_USERNAME"
ADMIN_PASSWORD_ENV = "AXIS_IDP_ADMIN_PASSWORD"
ADMIN_REALM_ENV = "AXIS_IDP_ADMIN_REALM"
ADMIN_CLIENT_ID_ENV = "AXIS_IDP_ADMIN_CLIENT_ID"


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="axis-bootstrap-keycloak-realm",
        description=(
            "Declare or verify the Axis tenant attribute, canonical realm roles, "
            "and web console client on an existing or fresh Keycloak realm. "
            "Safe to re-run; conflicts fail closed without writing."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("check", "apply"),
        default="check",
        help="check = dry-run plan only; apply = converge the realm",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AXIS_IDP_BASE_URL", "http://127.0.0.1:8080"),
        help="Keycloak base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--realm",
        default="axis",
        help="Realm to declare or verify (default: %(default)s)",
    )
    parser.add_argument(
        "--client-id",
        default=os.environ.get("AXIS_OIDC_CLIENT_ID", "limes-axis-web"),
        help="Web console client id (default: %(default)s)",
    )
    parser.add_argument(
        "--redirect-uri",
        action="append",
        dest="redirect_uris",
        default=[],
        help="Console OIDC redirect URI; repeat for each entry (required once)",
    )
    parser.add_argument(
        "--web-origin",
        action="append",
        dest="web_origins",
        default=[],
        help="Console CORS web origin; repeat for each entry (required once)",
    )
    parser.add_argument(
        "--post-logout-uri",
        action="append",
        dest="post_logout_redirect_uris",
        default=[],
        help="Post-logout redirect URI; repeat for each entry (required once)",
    )
    parser.add_argument(
        "--audience",
        default=os.environ.get("AXIS_OIDC_AUDIENCE", "limes-axis-api"),
        help="API audience the client tokens must carry (default: %(default)s)",
    )
    return parser


def spec_from_arguments(
    arguments: argparse.Namespace,
    *,
    parser: argparse.ArgumentParser,
) -> AxisRealmSpec:
    missing = [
        flag
        for flag, values in (
            ("--redirect-uri", arguments.redirect_uris),
            ("--web-origin", arguments.web_origins),
            ("--post-logout-uri", arguments.post_logout_redirect_uris),
        )
        if not values
    ]
    if missing:
        parser.error("missing required arguments: " + ", ".join(missing))
    return AxisRealmSpec(
        realm=arguments.realm,
        client=AxisIdpClientSpec(
            client_id=arguments.client_id,
            redirect_uris=arguments.redirect_uris,
            web_origins=arguments.web_origins,
            post_logout_redirect_uris=arguments.post_logout_redirect_uris,
            audience=arguments.audience,
        ),
    )


def run_cli(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    arguments = parser.parse_args(argv)
    spec = spec_from_arguments(arguments, parser=parser)

    admin_username = os.environ.get(ADMIN_USERNAME_ENV)
    admin_password = os.environ.get(ADMIN_PASSWORD_ENV)
    if not admin_username or not admin_password:
        print(
            f"Set {ADMIN_USERNAME_ENV} and {ADMIN_PASSWORD_ENV} in the environment; "
            "admin credentials are never accepted on the command line.",
            file=sys.stderr,
        )
        return 2

    adapter = UrllibKeycloakAdminHttp(
        base_url=arguments.base_url,
        admin_username=admin_username,
        admin_password=admin_password,
        admin_realm=os.environ.get(ADMIN_REALM_ENV, "master"),
        admin_client_id=os.environ.get(ADMIN_CLIENT_ID_ENV, "admin-cli"),
    )

    try:
        if arguments.mode == "apply":
            report = apply_realm(adapter, spec)
        else:
            report = check_realm(adapter, spec)
    except KeycloakBootstrapUnavailable as exc:
        print(
            json.dumps(
                {
                    "mode": arguments.mode,
                    "realm": spec.realm,
                    "status": "unreachable",
                    "reason": exc.reason,
                }
            ),
        )
        return 1

    print(report.model_dump_json(indent=2))
    return 0 if report.ok else 2


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
