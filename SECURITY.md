# Security Policy

Limes Axis is early commercial infrastructure in a private repository. Please
report suspected security issues privately and avoid opening public issues with
exploit details, secrets, personal data, customer data or proprietary logs.

## Supported Versions

The private repository currently supports the `main` branch only.

## Reporting A Vulnerability

Until a dedicated security contact is published, please use GitHub private
vulnerability reporting for this repository if available.

If private vulnerability reporting is unavailable, open a minimal public issue
that says a private security report is needed, without including exploit details
or sensitive information.

## Security Baseline

The Axis commercial source should preserve these defaults:

- no required managed services;
- no external model or data egress by default;
- tenant context on operational requests;
- typed actions with permission and approval checks;
- append-only audit evidence for important operations;
- pinned or versioned production runtime dependencies.

## Scope

Security reports may cover:

- tenant isolation;
- permission or approval bypass;
- audit tampering;
- external data/model egress bypass;
- unsafe default configuration;
- dependency or container risks;
- authentication and OIDC boundary issues.
