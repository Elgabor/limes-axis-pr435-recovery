.PHONY: install lint test typecheck build-web docs-check edition-matrix-check edition-export-readiness openapi openapi-check route-inventory route-inventory-check test-sdk security-check deployment-check deployment-profile-render-check deployment-rollout-rehearsal-plan deployment-rollout-rehearsal deployment-ha-rehearsal-plan deployment-ha-rehearsal deployment-load-rehearsal-plan deployment-load-rehearsal deployment-tls-readiness-plan deployment-tls-readiness deployment-backup-rehearsal-plan deployment-backup-rehearsal deployment-restore-rehearsal-plan deployment-restore-rehearsal deployment-typedb-recovery-rehearsal-plan deployment-typedb-recovery-rehearsal deployment-object-storage-recovery-rehearsal-plan deployment-object-storage-recovery-rehearsal deployment-temporal-recovery-rehearsal-plan deployment-temporal-recovery-rehearsal deployment-secret-rotation-rehearsal-plan deployment-secret-rotation-rehearsal container-check container-release-check container-security-check vulnerability-management-check container-build-api container-build-web container-build-worker container-build container-scan-local worker test-api test-model-persistence-postgres test-worker test-web test-integration test-e2e-connectors-source dev-stack-up dev-stack-down demo-stack-up demo-stack-down demo-db-upgrade demo-api demo-api-sso demo-web demo-keycloak-check demo-keycloak-bootstrap-check demo-check demo-check-live demo-verify demo-backup-plan demo-backup-local demo-restore-local

.PHONY: verify test-schemas test-e2e-smoke benchmark-lineage settings-reference settings-reference-check

PYTEST_ARGS ?=
WEB_TEST_ARGS ?=
BENCHMARK_ARGS ?=
AXIS_API_PORT ?= 8000
AXIS_WEB_PORT ?= 3000
AXIS_SOURCE_API_PORT ?= 8001
AXIS_ENV_FILE ?= $(CURDIR)/.env
# python-dotenv preserves unquoted JSON arrays in .env.example; uv's dotenv
# parser treats their quotes as shell quoting. Keep the application's parser.
DEV_RUN = uv run python -m dotenv -f "$(AXIS_ENV_FILE)" run --no-override --

install:
	pnpm install --frozen-lockfile
	cd services/api && uv sync --locked
	cd services/worker && uv sync --locked
	cd packages/sdk-python && uv sync --locked

lint:
	pnpm lint
	cd services/api && uv run ruff check --config pyproject.toml . ../../scripts/prepare_oss_export.py
	cd services/worker && uv run ruff check .
	cd packages/sdk-python && uv run ruff check .

typecheck:
	pnpm typecheck

test: test-api test-worker test-sdk test-web test-schemas

# Local component gates from CI, plus the existing demo/security contracts.
# Live-service and browser lanes remain explicit; see docs/development.md.
verify: lint typecheck test build-web openapi-check docs-check demo-check security-check deployment-check deployment-profile-render-check container-check container-release-check container-security-check vulnerability-management-check

test-api:
	cd services/api && uv run pytest $(PYTEST_ARGS)

# Runs the same facade/aggregate contract suite against a fresh migrated database.
test-model-persistence-postgres:
	@test -n "$${AXIS_MODEL_CONTRACT_POSTGRES_DSN}" || (echo "Set AXIS_MODEL_CONTRACT_POSTGRES_DSN to an isolated PostgreSQL server with CREATEDB"; exit 1)
	cd services/api && AXIS_MODEL_CONTRACT_BACKEND=postgresql uv run pytest tests/test_model_persistence_contract.py -q

test-worker:
	cd services/worker && uv run pytest $(PYTEST_ARGS)

test-sdk:
	cd packages/sdk-python && uv run pytest $(PYTEST_ARGS)

test-web:
	pnpm --filter @limes-axis/web test $(WEB_TEST_ARGS)

test-schemas:
	pnpm --filter @limes-axis/schemas test

test-e2e-smoke:
	pnpm --filter @limes-axis/web test:e2e:smoke

benchmark-lineage:
	cd services/api && uv run python scripts/benchmark_lineage.py $(BENCHMARK_ARGS)

settings-reference:
	cd services/api && uv run python scripts/export_settings_reference.py

settings-reference-check:
	cd services/api && uv run python scripts/export_settings_reference.py --check

test-integration:
	cd services/api && AXIS_RUN_INTEGRATION=1 uv run pytest tests/integration
	cd services/worker && AXIS_RUN_INTEGRATION=1 uv run pytest tests/integration

build-web:
	pnpm --filter @limes-axis/web build

docs-check: edition-matrix-check
	python3 scripts/check_documentation_paths.py

edition-matrix-check:
	python3 scripts/check_edition_matrix.py

edition-export-readiness:
	python3 scripts/check_edition_matrix.py --require-export-ready

openapi:
	cd services/api && uv run python scripts/export_openapi.py ../../docs/openapi.json

route-inventory:
	cd services/api && uv run python scripts/export_route_inventory.py --write

route-inventory-check:
	cd services/api && uv run python scripts/export_route_inventory.py

# Repository-local connector source lane: builds the web bundle against the
# lane API on AXIS_SOURCE_API_PORT (never the user-owned :8000 process), then runs
# the discovery, activation, and ingestion Playwright lanes on Chromium and
# mobile.
test-e2e-connectors-source:
	cd apps/web && NEXT_PUBLIC_AXIS_API_BASE_URL=http://127.0.0.1:$(AXIS_SOURCE_API_PORT) AXIS_E2E_LIVE_API=1 pnpm exec next build
	cd apps/web && AXIS_E2E_LIVE_API=1 AXIS_E2E_API_BASE_URL=http://127.0.0.1:$(AXIS_SOURCE_API_PORT) pnpm exec playwright test e2e/connectors-source-discovery.spec.ts e2e/connectors-source-activation.spec.ts e2e/connectors-source-ingestion.spec.ts --project=chromium --project=mobile

openapi-check:
	@schema_file=$$(mktemp "$${TMPDIR:-/tmp}/axis-openapi.XXXXXX") || exit 1; \
	trap 'rm -f "$$schema_file"' EXIT HUP INT TERM; \
	(cd services/api && uv run python scripts/export_openapi.py "$$schema_file") && \
	diff -u docs/openapi.json "$$schema_file"

security-check:
	cd services/api && uv run python scripts/check_security_posture.py

deployment-check:
	cd services/api && uv run python scripts/check_deployment_package.py

deployment-profile-render-check:
	cd services/api && uv run python scripts/check_helm_profile_renders.py

deployment-rollout-rehearsal-plan:
	cd services/api && uv run python scripts/rehearse_deployment_rollout.py --repo-root ../.. --plan

deployment-rollout-rehearsal:
	@test -n "$(AXIS_KUBE_CONTEXT)" || (echo "Set AXIS_KUBE_CONTEXT to the Kubernetes context to rehearse against"; exit 2)
	cd services/api && uv run python scripts/rehearse_deployment_rollout.py --repo-root ../.. --execute --context "$(AXIS_KUBE_CONTEXT)" $(AXIS_DEPLOYMENT_ROLLOUT_ARGS)

deployment-ha-rehearsal-plan:
	cd services/api && uv run python scripts/rehearse_ha_restart.py --repo-root ../.. --plan

deployment-ha-rehearsal:
	@test -n "$(AXIS_KUBE_CONTEXT)" || (echo "Set AXIS_KUBE_CONTEXT to the Kubernetes context to rehearse against"; exit 2)
	cd services/api && uv run python scripts/rehearse_ha_restart.py --repo-root ../.. --execute --context "$(AXIS_KUBE_CONTEXT)" $(AXIS_DEPLOYMENT_HA_ARGS)

deployment-load-rehearsal-plan:
	cd services/api && uv run python scripts/rehearse_load.py --repo-root ../.. --plan

deployment-load-rehearsal:
	@test -n "$(AXIS_KUBE_CONTEXT)" || (echo "Set AXIS_KUBE_CONTEXT to the Kubernetes context to rehearse against"; exit 2)
	cd services/api && uv run python scripts/rehearse_load.py --repo-root ../.. --execute --context "$(AXIS_KUBE_CONTEXT)" $(AXIS_DEPLOYMENT_LOAD_ARGS)

deployment-tls-readiness-plan:
	cd services/api && uv run python scripts/rehearse_tls_readiness.py --repo-root ../.. --plan

deployment-tls-readiness:
	@test -n "$(AXIS_KUBE_CONTEXT)" || (echo "Set AXIS_KUBE_CONTEXT to the Kubernetes context to rehearse against"; exit 2)
	cd services/api && uv run python scripts/rehearse_tls_readiness.py --repo-root ../.. --execute --context "$(AXIS_KUBE_CONTEXT)" $(AXIS_DEPLOYMENT_TLS_ARGS)

deployment-backup-rehearsal-plan:
	cd services/api && uv run python scripts/rehearse_production_backup.py --repo-root ../.. --plan

deployment-backup-rehearsal:
	@test -n "$(AXIS_KUBE_CONTEXT)" || (echo "Set AXIS_KUBE_CONTEXT to the Kubernetes context to rehearse against"; exit 2)
	cd services/api && uv run python scripts/rehearse_production_backup.py --repo-root ../.. --execute --context "$(AXIS_KUBE_CONTEXT)" $(AXIS_PRODUCTION_BACKUP_ARGS)

deployment-restore-rehearsal-plan:
	cd services/api && uv run python scripts/rehearse_production_restore.py --repo-root ../.. --plan

deployment-restore-rehearsal:
	@test -n "$(AXIS_KUBE_CONTEXT)" || (echo "Set AXIS_KUBE_CONTEXT to the Kubernetes context to rehearse against"; exit 2)
	cd services/api && uv run python scripts/rehearse_production_restore.py --repo-root ../.. --execute --context "$(AXIS_KUBE_CONTEXT)" $(AXIS_PRODUCTION_RESTORE_ARGS)

deployment-typedb-recovery-rehearsal-plan:
	cd services/api && uv run python scripts/rehearse_typedb_recovery.py --repo-root ../.. --plan

deployment-typedb-recovery-rehearsal:
	@test -n "$(AXIS_KUBE_CONTEXT)" || (echo "Set AXIS_KUBE_CONTEXT to the Kubernetes context to rehearse against"; exit 2)
	@test -n "$(AXIS_TYPEDB_RECOVERY_IMAGE)" || (echo "Set AXIS_TYPEDB_RECOVERY_IMAGE to a container image that includes TypeDB Console"; exit 2)
	cd services/api && uv run python scripts/rehearse_typedb_recovery.py --repo-root ../.. --execute --context "$(AXIS_KUBE_CONTEXT)" --image "$(AXIS_TYPEDB_RECOVERY_IMAGE)" $(AXIS_TYPEDB_RECOVERY_ARGS)

deployment-object-storage-recovery-rehearsal-plan:
	cd services/api && uv run python scripts/rehearse_object_storage_recovery.py --repo-root ../.. --plan

deployment-object-storage-recovery-rehearsal:
	@test -n "$(AXIS_KUBE_CONTEXT)" || (echo "Set AXIS_KUBE_CONTEXT to the Kubernetes context to rehearse against"; exit 2)
	@test -n "$(AXIS_OBJECT_STORAGE_RECOVERY_IMAGE)" || (echo "Set AXIS_OBJECT_STORAGE_RECOVERY_IMAGE to a container image that includes MinIO Client"; exit 2)
	cd services/api && uv run python scripts/rehearse_object_storage_recovery.py --repo-root ../.. --execute --context "$(AXIS_KUBE_CONTEXT)" --image "$(AXIS_OBJECT_STORAGE_RECOVERY_IMAGE)" $(AXIS_OBJECT_STORAGE_RECOVERY_ARGS)

deployment-temporal-recovery-rehearsal-plan:
	cd services/api && uv run python scripts/rehearse_temporal_recovery.py --repo-root ../.. --plan

deployment-temporal-recovery-rehearsal:
	@test -n "$(AXIS_KUBE_CONTEXT)" || (echo "Set AXIS_KUBE_CONTEXT to the Kubernetes context to rehearse against"; exit 2)
	@test -n "$(AXIS_TEMPORAL_RECOVERY_IMAGE)" || (echo "Set AXIS_TEMPORAL_RECOVERY_IMAGE to a container image that includes Temporal CLI"; exit 2)
	cd services/api && uv run python scripts/rehearse_temporal_recovery.py --repo-root ../.. --execute --context "$(AXIS_KUBE_CONTEXT)" --image "$(AXIS_TEMPORAL_RECOVERY_IMAGE)" $(AXIS_TEMPORAL_RECOVERY_ARGS)

deployment-secret-rotation-rehearsal-plan:
	cd services/api && uv run python scripts/rehearse_secret_rotation.py --repo-root ../.. --plan

deployment-secret-rotation-rehearsal:
	@test -n "$(AXIS_KUBE_CONTEXT)" || (echo "Set AXIS_KUBE_CONTEXT to the Kubernetes context to rehearse against"; exit 2)
	@test -n "$(AXIS_SECRET_ROTATION_IMAGE)" || (echo "Set AXIS_SECRET_ROTATION_IMAGE to a container image that includes sh, cmp and sha256sum"; exit 2)
	cd services/api && uv run python scripts/rehearse_secret_rotation.py --repo-root ../.. --execute --context "$(AXIS_KUBE_CONTEXT)" --image "$(AXIS_SECRET_ROTATION_IMAGE)" $(AXIS_SECRET_ROTATION_ARGS)

container-check:
	cd services/api && uv run python scripts/check_container_images.py

container-release-check:
	cd services/api && uv run python scripts/check_container_release.py

container-security-check:
	cd services/api && uv run python scripts/check_container_security_scan.py

vulnerability-management-check:
	cd services/api && uv run python scripts/check_vulnerability_management.py

container-build-api:
	docker build -f services/api/Dockerfile -t limes-axis-api:local .

container-build-web:
	docker build -f apps/web/Dockerfile -t limes-axis-web:local .

container-build-worker:
	docker build -f services/worker/Dockerfile -t limes-axis-worker:local .

container-build: container-build-api container-build-web container-build-worker

container-scan-local: container-build
	mkdir -p .axis/trivy-cache .axis/trivy-reports
	docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$$(pwd)/.axis/trivy-cache:/root/.cache/" -v "$$(pwd)/.axis/trivy-reports:/reports" aquasec/trivy:0.71.2 image --scanners vuln --pkg-types os,library --severity CRITICAL --ignore-unfixed --exit-code 1 --format json --output /reports/api-critical.json --timeout 10m limes-axis-api:local
	docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$$(pwd)/.axis/trivy-cache:/root/.cache/" -v "$$(pwd)/.axis/trivy-reports:/reports" aquasec/trivy:0.71.2 image --scanners vuln --pkg-types os,library --severity CRITICAL --ignore-unfixed --exit-code 1 --format json --output /reports/web-critical.json --timeout 10m limes-axis-web:local
	docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$$(pwd)/.axis/trivy-cache:/root/.cache/" -v "$$(pwd)/.axis/trivy-reports:/reports" aquasec/trivy:0.71.2 image --scanners vuln --pkg-types os,library --severity CRITICAL --ignore-unfixed --exit-code 1 --format json --output /reports/worker-critical.json --timeout 10m limes-axis-worker:local
	@echo "Trivy reports saved under .axis/trivy-reports/"

dev-stack-up:
	docker compose -f infra/docker/docker-compose.yml up -d

dev-stack-down:
	docker compose -f infra/docker/docker-compose.yml down

demo-stack-up: dev-stack-up

demo-stack-down: dev-stack-down

demo-db-upgrade:
	cd services/api && $(DEV_RUN) alembic upgrade head

demo-api:
	cd services/api && $(DEV_RUN) uvicorn axis_api.main:create_app --factory --host 127.0.0.1 --port $(AXIS_API_PORT)

worker:
	cd services/worker && $(DEV_RUN) python -m axis_worker

demo-api-sso:
	cd services/api && AXIS_PUBLIC_BASE_URL=http://127.0.0.1:3000 AXIS_API_BASE_URL=http://127.0.0.1:8000 AXIS_OIDC_ISSUER=http://127.0.0.1:8080/realms/axis AXIS_OIDC_JWKS_URL=http://127.0.0.1:8080/realms/axis/protocol/openid-connect/certs AXIS_OIDC_CLIENT_ID=limes-axis-web AXIS_OIDC_CLIENT_SECRET=axis-local-dev-secret AXIS_OIDC_AUTHORIZATION_URL=http://127.0.0.1:8080/realms/axis/protocol/openid-connect/auth AXIS_OIDC_TOKEN_URL=http://127.0.0.1:8080/realms/axis/protocol/openid-connect/token AXIS_OIDC_REDIRECT_URI=http://127.0.0.1:8000/identity/oidc/callback AXIS_OIDC_END_SESSION_URL=http://127.0.0.1:8080/realms/axis/protocol/openid-connect/logout AXIS_OIDC_POST_LOGOUT_REDIRECT_URI=http://127.0.0.1:3000/ AXIS_OIDC_SESSION_COOKIE_SIGNING_SECRET=axis-local-demo-session-signing-key AXIS_OIDC_SESSION_COOKIE_SECURE=false uv run uvicorn axis_api.main:create_app --factory --host 127.0.0.1 --port 8000

demo-web:
	NEXT_PUBLIC_AXIS_API_BASE_URL=http://127.0.0.1:$(AXIS_API_PORT) pnpm --filter @limes-axis/web dev --port $(AXIS_WEB_PORT)

demo-keycloak-check:
	cd services/api && uv run python scripts/check_demo_environment.py --keycloak-url http://127.0.0.1:8080

# Read-only verification of the LOCAL DEMO realm against the canonical
# bootstrap boundary. Local demo values only; enterprise realms use
# services/api/scripts/bootstrap_keycloak_realm.py with their own values.
demo-keycloak-bootstrap-check:
	cd services/api && \
	AXIS_IDP_ADMIN_USERNAME=$${AXIS_IDP_ADMIN_USERNAME:-axis} \
	AXIS_IDP_ADMIN_PASSWORD=$${AXIS_IDP_ADMIN_PASSWORD:-axis-axis} \
	uv run python scripts/bootstrap_keycloak_realm.py \
		--base-url http://127.0.0.1:8080 \
		--realm axis \
		--client-id limes-axis-web \
		--redirect-uri http://127.0.0.1:8000/identity/oidc/callback \
		--redirect-uri http://localhost:8000/identity/oidc/callback \
		--web-origin 'http://127.0.0.1:3000/*' \
		--web-origin 'http://localhost:3000/*' \
		--post-logout-uri 'http://127.0.0.1:3000/*' \
		--post-logout-uri 'http://localhost:3000/*' \
		--mode check

demo-check:
	cd services/api && uv run python scripts/check_demo_environment.py

demo-check-live:
	cd services/api && uv run python scripts/check_demo_environment.py --api-url http://127.0.0.1:$(AXIS_API_PORT) --web-url http://127.0.0.1:$(AXIS_WEB_PORT)

demo-verify: openapi-check demo-check deployment-profile-render-check

demo-backup-plan:
	cd services/api && uv run python scripts/demo_backup_restore.py --repo-root ../.. plan

demo-backup-local:
	cd services/api && uv run python scripts/demo_backup_restore.py --repo-root ../.. backup

demo-restore-local:
	@test -n "$(AXIS_BACKUP_DIR)" || (echo "Set AXIS_BACKUP_DIR=.axis/backups/<backup-id>"; exit 2)
	cd services/api && uv run python scripts/demo_backup_restore.py --repo-root ../.. restore --backup-dir "$(AXIS_BACKUP_DIR)" --confirm-restore
