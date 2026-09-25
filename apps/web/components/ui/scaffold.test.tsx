import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DetailGrid, KeyValueRow } from "@/components/ui/detail-grid";
import { FilterBar, type FilterDef } from "@/components/ui/filter-bar";
import { Term } from "@/components/ui/glossary";
import { InspectDrawer } from "@/components/ui/inspect-drawer";
import { MasterDetail } from "@/components/ui/master-detail";
import { MetricStrip, type Metric } from "@/components/ui/metric-strip";
import { PageHeader } from "@/components/ui/page-header";
import { glossary } from "@/lib/strings";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PageHeader", () => {
  it("renders one title with its purpose and actions", () => {
    render(
      <PageHeader
        actions={<button type="button">Add connector</button>}
        description="Review and decide on actions agents have proposed."
        title="Approvals"
      />,
    );

    expect(screen.queryByText("Operate")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Approvals" })).toBeInTheDocument();
    expect(
      screen.getByText("Review and decide on actions agents have proposed."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add connector" })).toBeInTheDocument();
  });
});

describe("MetricStrip", () => {
  const sixMetrics: Metric[] = [
    { label: "Connectors", value: 4, tone: "ready" },
    { label: "Runs", value: 12 },
    { label: "Pending proposals", value: 2, tone: "watch" },
    { label: "Egress policies", value: 3 },
    { label: "Evidence issues", value: 1, tone: "action" },
    { label: "Extra metric", value: 9 },
  ];

  it("renders at most 5 metrics and warns in dev when given more", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    render(<MetricStrip metrics={sixMetrics} />);

    expect(screen.getByText("Connectors")).toBeInTheDocument();
    expect(screen.getByText("Evidence issues")).toBeInTheDocument();
    expect(screen.queryByText("Extra metric")).not.toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it("does not warn when given 5 or fewer", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    render(<MetricStrip metrics={sixMetrics.slice(0, 3)} />);
    expect(warn).not.toHaveBeenCalled();
  });
});

describe("FilterBar", () => {
  const filters: FilterDef[] = [
    {
      id: "state",
      label: "State",
      options: [
        { value: "all", label: "All states" },
        { value: "running", label: "Running" },
      ],
    },
    {
      id: "domain",
      label: "Domain",
      options: [
        { value: "all", label: "All domains" },
        { value: "quality", label: "Quality" },
      ],
    },
  ];

  it("wires onChange per filter and onReset via a visible Reset label", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onReset = vi.fn();
    render(
      <FilterBar
        filters={filters}
        values={{ state: "all", domain: "all" }}
        onChange={onChange}
        onReset={onReset}
      />,
    );

    await user.selectOptions(screen.getByLabelText("State"), "running");
    expect(onChange).toHaveBeenCalledWith("state", "running");

    await user.click(screen.getByRole("button", { name: "Reset" }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });
});

describe("MasterDetail", () => {
  it("renders list and detail regions", () => {
    render(<MasterDetail detail={<p>Detail pane</p>} list={<p>List pane</p>} />);
    expect(screen.getByText("List pane")).toBeInTheDocument();
    expect(screen.getByText("Detail pane")).toBeInTheDocument();
  });
});

describe("DetailGrid / KeyValueRow", () => {
  it("renders label/value pairs", () => {
    render(
      <DetailGrid>
        <KeyValueRow label="Owner">Quality team</KeyValueRow>
        <KeyValueRow mono label="Tenant">
          tenant_demo_manufacturing
        </KeyValueRow>
      </DetailGrid>,
    );

    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.getByText("Quality team")).toBeInTheDocument();
    expect(screen.getByText("tenant_demo_manufacturing")).toBeInTheDocument();
  });
});

describe("InspectDrawer", () => {
  const record = {
    connector_id: "conn_file_csv_01",
    status: "active",
    manifest: { revision: 3, egress: false },
  };

  it("opens from the default Inspect trigger and shows flattened fields plus raw JSON", async () => {
    const user = userEvent.setup();
    render(<InspectDrawer record={record} title="Connector record" />);

    await user.click(screen.getByRole("button", { name: "Inspect" }));
    expect(await screen.findByText("Connector record")).toBeInTheDocument();

    // Fields tab (default): flattened key/value rows.
    const fieldsPanel = screen.getByRole("tabpanel");
    expect(within(fieldsPanel).getByText("connector_id")).toBeInTheDocument();
    expect(within(fieldsPanel).getByText("conn_file_csv_01")).toBeInTheDocument();
    expect(within(fieldsPanel).getByText("manifest.revision")).toBeInTheDocument();
    expect(within(fieldsPanel).getByText("3")).toBeInTheDocument();

    // Raw tab: pretty-printed JSON.
    await user.click(screen.getByRole("tab", { name: "Raw" }));
    const rawPanel = screen.getByRole("tabpanel");
    expect(rawPanel.textContent).toContain('"connector_id": "conn_file_csv_01"');
    expect(rawPanel.textContent).toContain('"revision": 3');
  });
});

describe("Term", () => {
  it("renders the glossary label with a tooltip definition on focus", async () => {
    const user = userEvent.setup();
    render(<Term k="autonomy_level" />);

    expect(screen.getByText(glossary.autonomy_level.label)).toBeInTheDocument();

    await user.tab();
    const matches = await screen.findAllByText(glossary.autonomy_level.definition);
    expect(matches.length).toBeGreaterThan(0);
  });

  it("supports custom child text", () => {
    render(<Term k="egress">outbound data</Term>);
    expect(screen.getByText("outbound data")).toBeInTheDocument();
  });
});
