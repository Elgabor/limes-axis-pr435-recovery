import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, type APIRequestContext } from "@playwright/test";

import { AXIS_API_BASE_URL, DEMO_TENANT_ID } from "./axis-api";

/*
 * Shared seams for the live external-DB source lanes (discovery + activation).
 *
 * The console's external-DB connector verifies connectivity and runs bounded
 * schema discovery against a throwaway Postgres schema on the same Docker
 * source database the API is configured with (AXIS_EXTERNAL_DB_LIVE_QUERY_DSN).
 * The allowlisted source schema name is fixed at API start-up
 * (AXIS_EXTERNAL_DB_DISCOVERY_SCHEMAS including axis_e2e_source); these helpers
 * create tokenized tables inside it through `docker compose exec` because Axis
 * has no SQL surface by design.
 *
 * Hygiene contract: rows and tables persist under their `_e2e_discovery_`
 * prefix; binding ids persist under their `_e2e_activation_` prefix. Nothing
 * deletes demo-tenant records through Axis.
 */

export const SOURCE_SCHEMA = process.env.AXIS_E2E_DISCOVERY_SCHEMA ?? "axis_e2e_source";
const REPO_COMPOSE_FILE = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "..",
  "..",
  "infra",
  "docker",
  "docker-compose.yml",
);

export function createSourceTables(token: string): string[] {
  // scopedRunToken embeds the Playwright project name as its first segment,
  // which doubles as the per-project cleanup namespace.
  const project = token.split("_")[0];
  const tableNames = [
    `production_orders_${token}`,
    `quality_checks_${token}`,
  ];
  // Prior RUNS of the same project are removed so this run's discovery is
  // the FIRST observation of everything it lists (drift = added), the
  // allowlisted schema stays inside the deployment's bounded table limit,
  // and parallel projects (chromium/mobile) never race on each other's tables.
  const sql = [
    `CREATE SCHEMA IF NOT EXISTS ${SOURCE_SCHEMA}`,
    `DO $$ DECLARE t record; BEGIN
       FOR t IN SELECT tablename FROM pg_tables
       WHERE schemaname = '${SOURCE_SCHEMA}'
         AND tablename ~ '(production_orders|quality_checks)_${project}_'
         AND tablename NOT IN (${tableNames.map((t) => `'${t}'`).join(", ")})
       LOOP EXECUTE format('DROP TABLE IF EXISTS ${SOURCE_SCHEMA}.%I CASCADE', t.tablename); END LOOP;
     END $$;`,
    ...tableNames.map(
      (table) =>
        `CREATE TABLE IF NOT EXISTS ${SOURCE_SCHEMA}.${table} (` +
        `${table}_id text PRIMARY KEY, asset_id text NOT NULL, status text)`,
    ),
  ].join("; ");
  execFileSync(
    "docker",
    [
      "compose",
      "-f",
      REPO_COMPOSE_FILE,
      "exec",
      "-T",
      "postgres",
      "psql",
      "-U",
      "axis",
      "-d",
      "axis",
      "-v",
      "ON_ERROR_STOP=1",
      "-c",
      sql,
    ],
    { stdio: "pipe" },
  );
  return tableNames;
}

/** Real drift at the source: add a column to one of this run's tables. */
export function addColumnToSourceTable(token: string, tableName: string): void {
  const sql =
    `ALTER TABLE ${SOURCE_SCHEMA}.${tableName} `
    + "ADD COLUMN severity text NOT NULL DEFAULT 'low'";
  execFileSync(
    "docker",
    [
      "compose",
      "-f",
      REPO_COMPOSE_FILE,
      "exec",
      "-T",
      "postgres",
      "psql",
      "-U",
      "axis",
      "-d",
      "axis",
      "-v",
      "ON_ERROR_STOP=1",
      "-c",
      sql,
    ],
    { stdio: "pipe" },
  );
}

export async function seedGovernanceRecords(
  request: APIRequestContext,
  token: string,
): Promise<{ leaseId: string; policyId: string }> {  const handleId = `cred_e2e_discovery_${token}`;
  const leaseId = `lease_e2e_discovery_${token}`;
  const policyId = `egress_policy_e2e_discovery_${token}`;

  const handle = await request.post(`${AXIS_API_BASE_URL}/operations/connectors/credential-handles`, {
    data: {
      tenant_id: DEMO_TENANT_ID,
      connector_id: "external_db_operational_mirror",
      handle_id: handleId,
      display_name: `E2E discovery readonly credential ${token}`,
      secret_provider: "env",
      secret_ref: "vault://axis/e2e/connectors/source-discovery-readonly",
      purpose: "e2e_source_discovery",
      created_by: "platform-connector-owner-role",
    },
  });
  expect(handle.status(), await handle.text()).toBe(201);

  const lease = await request.post(`${AXIS_API_BASE_URL}/operations/connectors/credential-leases`, {
    data: {
      tenant_id: DEMO_TENANT_ID,
      connector_id: "external_db_operational_mirror",
      handle_id: handleId,
      lease_id: leaseId,
      requested_by: "connector-console-operator",
      actor_scopes: ["connectors:credential_lease:request"],
      required_scopes: ["connectors:credential_lease:request"],
      lease_purpose: "e2e_source_discovery",
    },
  });
  expect(lease.status(), await lease.text()).toBe(201);

  // The API pins its DSN to localhost:5432; egress enforcement compares this
  // approved hash with the actual connect target at runtime.
  const endpointTargetSha256 = createHash("sha256")
    .update("localhost:5432")
    .digest("hex");
  // Runtime egress enforcement compares the policy's named endpoint and the
  // approved target hash against the deployment-pinned profile, so an operator
  // policy MUST reference the same private endpoint the profile pins —
  // anything else is correctly blocked before connecting.
  const policy = await request.post(`${AXIS_API_BASE_URL}/operations/connectors/egress-policies`, {
    data: {
      tenant_id: DEMO_TENANT_ID,
      connector_id: "external_db_operational_mirror",
      policy_id: policyId,
      display_name: `E2E discovery private endpoint ${token}`,
      connection_profile_id: "profile_postgres_discovery_readonly",
      egress_boundary: "approved_private_endpoint",
      policy_mode: "approved_private_endpoint",
      private_endpoint_ref:
        "private-endpoint://tenant_demo_manufacturing/persisted-operations-postgres-readonly",
      created_by: "platform-connector-owner-role",
      policy_document: { approved_endpoint_target_sha256: endpointTargetSha256 },
    },
  });
  expect(policy.status(), await policy.text()).toBe(201);

  return { leaseId, policyId };
}

/**
 * Run one bounded discovery through the real API as a concurrent observer
 * would. Used to refresh persisted observations after real source drift, so a
 * browser page still holding pre-drift fingerprints honestly hits the stale
 * rejection on its next activation attempt.
 */
export async function discoverSourceTables(
  request: APIRequestContext,
  input: { token: string; discoveryId: string; leaseId: string; policyId: string },
): Promise<Map<string, string>> {
  const response = await request.post(
    `${AXIS_API_BASE_URL}/operations/connectors/external-db/discover`,
    {
      data: {
        tenant_id: DEMO_TENANT_ID,
        connector_id: "external_db_operational_mirror",
        discovery_id: input.discoveryId,
        requested_by: "connector-console-operator",
        connection_profile_id: "profile_postgres_discovery_readonly",
        schema_name: SOURCE_SCHEMA,
        credential_lease_id: input.leaseId,
        egress_policy_id: input.policyId,
        actor_scopes: ["connectors:source:discover"],
      },
    },
  );
  expect(response.status(), await response.text()).toBe(200);
  const body = (await response.json()) as {
    result: {
      status: string;
      tables: Array<{ schema_name: string; table_name: string; column_fingerprint: string }>;
    };
  };
  expect(body.result.status).toBe("discovery_completed");
  return new Map(
    body.result.tables.map((table) => [
      `${table.schema_name}.${table.table_name}`,
      table.column_fingerprint,
    ]),
  );
}
