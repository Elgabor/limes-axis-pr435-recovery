.PHONY: install lint test typecheck build-web docs-check edition-matrix-check edition-export-readiness openapi openapi-check test-sdk security-check deployment-check deployment-profile-render-check deployment-rollout-rehearsal-plan deployment-rollout-rehearsal deployment-ha-rehearsal-plan deployment-ha-rehearsal deployment-load-rehearsal-plan deployment-load-rehearsal deployment-tls-readiness-plan deployment-tls-readiness deployment-backup-rehearsal-plan deployment-backup-rehearsal deployment-restore-rehearsal-plan deployment-restore-rehearsal deployment-typedb-recovery-rehearsal-plan deployment-typedb-recovery-rehearsal deployment-object-storage-recovery-rehearsal-plan deployment-object-storage-recovery-rehearsal deployment-temporal-recovery-rehearsal-plan deployment-temporal-recovery-rehearsal deployment-secret-rotation-rehearsal-plan deployment-secret-rotation-rehearsal container-check container-release-check container-security-check vulnerability-management-check container-build-api container-build-web container-build-worker container-build container-scan-local worker test-api test-worker test-web test-integration test-e2e-connectors-source dev-stack-up dev-stack-down demo-stack-up demo-stack-down demo-db-upgrade demo-api demo-api-sso demo-web demo-keycloak-check demo-keycloak-bootstrap-check demo-check demo-check-live demo-verify demo-backup-plan demo-backup-local demo-restore-local

install:
	pnpm install
	cd services/api && uv sync
	cd services/worker && uv sync
	cd packages/sdk-python && uv sync

lint:
	pnpm lint
	cd services/api && uv run ruff check .
	cd services/worker && uv run ruff check .
	cd packages/sdk-python && uv run ruff check .

typecheck:
	pnpm typecheck

test: test-api test-worker test-sdk test-web

test-api:
	cd services/api && uv run pytest

test-worker:
	cd services/worker && uv run pytest

test-sdk:
	cd packages/sdk-python && uv run pytest

test-web:
	pnpm --filter @limes-axis/web test

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

# Repository-local connector source lane: builds the web bundle against the
# lane API on 127.0.0.1:8001 (never the user-owned :8000 process), then runs
# the discovery, activation, and ingestion Playwright lanes on Chromium and
# mobile.
test-e2e-connectors-source:
	cd apps/web && NEXT_PUBLIC_AXIS_API_BASE_URL=http://127.0.0.1:8001 AXIS_E2E_LIVE_API=1 pnpm exec next build
	cd apps/web && AXIS_E2E_LIVE_API=1 AXIS_E2E_API_BASE_URL=http://127.0.0.1:8001 pnpm exec playwright test e2e/connectors-source-discovery.spec.ts e2e/connectors-source-activation.spec.ts e2e/connectors-source-ingestion.spec.ts --project=chromium --project=mobile

openapi-check:
	cd services/api && uv run python scripts/export_openapi.py /tmp/limes-axis-openapi.json
	diff -u docs/openapi.json /tmp/limes-axis-openapi.json

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
	cd services/api && uv run alembic upgrade head

demo-api:
	cd services/api && uv run uvicorn axis_api.main:create_app --factory --host 127.0.0.1 --port 8000

worker:
	cd services/worker && uv run python -m axis_worker

demo-api-sso:
	cd services/api && AXIS_PUBLIC_BASE_URL=http://127.0.0.1:3000 AXIS_API_BASE_URL=http://127.0.0.1:8000 AXIS_OIDC_ISSUER=http://127.0.0.1:8080/realms/axis AXIS_OIDC_JWKS_URL=http://127.0.0.1:8080/realms/axis/protocol/openid-connect/certs AXIS_OIDC_CLIENT_ID=limes-axis-web AXIS_OIDC_CLIENT_SECRET=axis-local-dev-secret AXIS_OIDC_AUTHORIZATION_URL=http://127.0.0.1:8080/realms/axis/protocol/openid-connect/auth AXIS_OIDC_TOKEN_URL=http://127.0.0.1:8080/realms/axis/protocol/openid-connect/token AXIS_OIDC_REDIRECT_URI=http://127.0.0.1:8000/identity/oidc/callback AXIS_OIDC_END_SESSION_URL=http://127.0.0.1:8080/realms/axis/protocol/openid-connect/logout AXIS_OIDC_POST_LOGOUT_REDIRECT_URI=http://127.0.0.1:3000/ AXIS_OIDC_SESSION_COOKIE_SIGNING_SECRET=axis-local-demo-session-signing-key AXIS_OIDC_SESSION_COOKIE_SECURE=false uv run uvicorn axis_api.main:create_app --factory --host 127.0.0.1 --port 8000

demo-web:
	NEXT_PUBLIC_AXIS_API_BASE_URL=http://127.0.0.1:8000 pnpm --filter @limes-axis/web dev

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
	cd services/api && uv run python scripts/check_demo_environment.py --api-url http://127.0.0.1:8000 --web-url http://127.0.0.1:3000

demo-verify: openapi-check demo-check deployment-profile-render-check

demo-backup-plan:
	cd services/api && uv run python scripts/demo_backup_restore.py --repo-root ../.. plan

demo-backup-local:
	cd services/api && uv run python scripts/demo_backup_restore.py --repo-root ../.. backup

demo-restore-local:
	@test -n "$(AXIS_BACKUP_DIR)" || (echo "Set AXIS_BACKUP_DIR=.axis/backups/<backup-id>"; exit 2)
	cd services/api && uv run python scripts/demo_backup_restore.py --repo-root ../.. restore --backup-dir "$(AXIS_BACKUP_DIR)" --confirm-restore
