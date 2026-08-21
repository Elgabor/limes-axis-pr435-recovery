import { describe, expect, it } from "vitest";

import { glossary, strings } from "./strings";

const consoleRoutes = [
  "overview",
  "agents",
  "approvals",
  "audit",
  "connectors",
  "model-routing",
  "ontology",
  "policies",
  "settings",
  "simulation",
  "tenants",
  "workflows",
] as const;

const glossaryKeys = [
  "ontology",
  "autonomy_level",
  "egress",
  "evidence",
  "dry_run",
  "replay",
  "idempotency",
  "connector_manifest",
  "policy_scope",
] as const;

const navGroupLabels = ["Operate", "Data & Models", "Governance", "Platform"];

describe("strings.pages", () => {
  it("has an entry for each of the 12 console routes", () => {
    for (const route of consoleRoutes) {
      expect(strings.pages[route], `missing page strings for "${route}"`).toBeDefined();
    }
    expect(Object.keys(strings.pages)).toHaveLength(consoleRoutes.length);
  });

  it("gives every page a non-empty eyebrow, title and one-sentence description", () => {
    for (const route of consoleRoutes) {
      const page = strings.pages[route];
      expect(page.eyebrow.length).toBeGreaterThan(0);
      expect(page.title.length).toBeGreaterThan(0);
      expect(page.description.length).toBeGreaterThan(0);
      expect(navGroupLabels).toContain(page.eyebrow);
    }
  });
});

describe("strings.nav", () => {
  it("exposes the four sidebar group labels", () => {
    // `strings.nav` also carries the footer's copy, so assert the group labels
    // are present rather than that they are the only entries.
    const navValues: string[] = Object.values(strings.nav);
    expect(navGroupLabels.every((label) => navValues.includes(label))).toBe(true);
    expect(strings.nav.help.length).toBeGreaterThan(0);
    expect(strings.nav.signedOut.length).toBeGreaterThan(0);
  });
});

describe("strings.states", () => {
  it("provides generic loading, error and empty copy", () => {
    expect(strings.states.loading.length).toBeGreaterThan(0);
    expect(strings.states.error.title.length).toBeGreaterThan(0);
    expect(strings.states.error.detail.length).toBeGreaterThan(0);
    expect(strings.states.error.retry.length).toBeGreaterThan(0);
    expect(strings.states.empty.title.length).toBeGreaterThan(0);
    expect(strings.states.empty.detail.length).toBeGreaterThan(0);
  });
});

describe("strings.approvals", () => {
  it("provides decision-flow, empty and error copy for the approval inbox", () => {
    const approvals = strings.approvals;
    expect(approvals.error.title.length).toBeGreaterThan(0);
    expect(approvals.error.detail).toContain("Local fallback approval records are disabled.");
    expect(approvals.empty.title.length).toBeGreaterThan(0);
    expect(approvals.empty.detail.length).toBeGreaterThan(0);
    expect(approvals.decision.confirmTitle.length).toBeGreaterThan(0);
    expect(approvals.decision.rationaleLabel.length).toBeGreaterThan(0);
    expect(approvals.decision.confirm.length).toBeGreaterThan(0);
    expect(approvals.decision.cancel.length).toBeGreaterThan(0);
    expect(approvals.decision.toastTitle.length).toBeGreaterThan(0);
    expect(approvals.decision.auditLink.length).toBeGreaterThan(0);
  });
});

describe("strings.workflows", () => {
  it("provides blocker, timeline, filter, empty and error copy for the workflow console", () => {
    const workflows = strings.workflows;
    expect(workflows.error.title).toBe("Workflow API unavailable");
    expect(workflows.error.detail).toContain("Local fallback workflow records are disabled.");
    expect(workflows.empty.title.length).toBeGreaterThan(0);
    expect(workflows.empty.detail.length).toBeGreaterThan(0);
    expect(workflows.noMatch.title.length).toBeGreaterThan(0);
    expect(workflows.noMatch.reset.length).toBeGreaterThan(0);
    expect(workflows.blocker.title.length).toBeGreaterThan(0);
    expect(workflows.blocker.linkNamed.length).toBeGreaterThan(0);
    expect(workflows.blocker.linkGeneric).toBe("Open approvals");
    expect(workflows.timeline.title.length).toBeGreaterThan(0);
    expect(workflows.sections.inputs.length).toBeGreaterThan(0);
    expect(workflows.sections.outputs.length).toBeGreaterThan(0);
    expect(workflows.sections.context.length).toBeGreaterThan(0);
    expect(workflows.inspect.length).toBeGreaterThan(0);
  });
});

describe("strings.tenantVocabulary", () => {
  it("provides editor, validation, source and configuration-state copy", () => {
    const vocabulary = strings.tenantVocabulary;
    expect(vocabulary.title).toBe("Console terminology");
    expect(vocabulary.mode.defaults.length).toBeGreaterThan(0);
    expect(vocabulary.mode.configured.length).toBeGreaterThan(0);
    expect(vocabulary.actions.addDomain.length).toBeGreaterThan(0);
    expect(vocabulary.validation.labelTooLong(100)).toContain("100");
    expect(vocabulary.errors.requiredPermission("Denied.", "tenant:configure")).toContain(
      "tenant:configure",
    );
  });
});

describe("glossary", () => {
  it("defines every platform term", () => {
    for (const key of glossaryKeys) {
      const entry = glossary[key];
      expect(entry, `missing glossary entry "${key}"`).toBeDefined();
      expect(entry.label.length).toBeGreaterThan(0);
      expect(entry.definition.length).toBeGreaterThan(20);
    }
    expect(Object.keys(glossary)).toHaveLength(glossaryKeys.length);
  });
});
