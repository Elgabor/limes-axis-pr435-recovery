import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EmptyPanel, ErrorPanel, LoadingPanel } from "./states";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("LoadingPanel", () => {
  it("renders skeleton blocks and no text", () => {
    const { container } = render(<LoadingPanel />);

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
    expect(container.textContent).toBe("");
  });

  it("renders the requested number of rows in list layout", () => {
    const { container } = render(<LoadingPanel layout="list" rows={4} />);

    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(4);
  });

  it("renders metric-shaped skeletons without text in metrics layout", () => {
    const { container } = render(<LoadingPanel layout="metrics" />);

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
    expect(container.textContent).toBe("");
  });
});

describe("ErrorPanel", () => {
  it("shows plain copy and hides the endpoint until technical details are expanded", async () => {
    const user = userEvent.setup();
    render(
      <ErrorPanel
        title="Approvals are unavailable"
        detail="The console could not reach the Axis API."
        endpoint={`${OPERATIONS_API_PREFIX}/approvals`}
      />,
    );

    expect(screen.getByText("Approvals are unavailable")).toBeInTheDocument();
    expect(screen.getByText("The console could not reach the Axis API.")).toBeInTheDocument();
    expect(screen.queryByText(`${OPERATIONS_API_PREFIX}/approvals`)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Technical details" }));

    expect(screen.getByText(`${OPERATIONS_API_PREFIX}/approvals`)).toBeInTheDocument();
  });

  it("reveals an operator reference only inside technical details", async () => {
    const user = userEvent.setup();
    render(
      <ErrorPanel
        title="Decision persistence error"
        detail="Axis could not persist the decision."
        reference="request-approval-503"
      />,
    );

    expect(screen.queryByText("request-approval-503")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Technical details" }));

    expect(screen.getByText("request-approval-503")).toBeInTheDocument();
    expect(screen.getByText("Reference")).toBeInTheDocument();
  });

  it("explains the default base URL inside technical details when no override is set", async () => {
    vi.stubEnv("NEXT_PUBLIC_AXIS_API_BASE_URL", "");
    const user = userEvent.setup();
    render(<ErrorPanel title="API unavailable" endpoint={`${OPERATIONS_API_PREFIX}/overview`} />);

    await user.click(screen.getByRole("button", { name: "Technical details" }));

    expect(
      screen.getByText(
        "Console is using the default http://localhost:8000 — set NEXT_PUBLIC_AXIS_API_BASE_URL if your API runs elsewhere.",
      ),
    ).toBeInTheDocument();
  });

  it("omits the default base URL note when an override is configured", async () => {
    vi.stubEnv("NEXT_PUBLIC_AXIS_API_BASE_URL", "https://axis.example.com");
    const user = userEvent.setup();
    render(<ErrorPanel title="API unavailable" endpoint={`${OPERATIONS_API_PREFIX}/overview`} />);

    await user.click(screen.getByRole("button", { name: "Technical details" }));

    expect(screen.queryByText(/default http:\/\/localhost:8000/)).not.toBeInTheDocument();
    expect(screen.getByText("https://axis.example.com")).toBeInTheDocument();
  });

  it("invokes onRetry from the retry button", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<ErrorPanel title="API unavailable" onRetry={onRetry} />);

    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe("EmptyPanel", () => {
  it("renders title, detail, and a link CTA when the action has an href", () => {
    render(
      <EmptyPanel
        title="No connectors yet"
        detail="Connect a data source to start governed syncs."
        action={{ label: "Add your first connector", href: "/connectors" }}
      />,
    );

    expect(screen.getByText("No connectors yet")).toBeInTheDocument();
    expect(screen.getByText("Connect a data source to start governed syncs.")).toBeInTheDocument();

    const cta = screen.getByRole("link", { name: "Add your first connector" });
    expect(cta).toHaveAttribute("href", "/connectors");
  });

  it("renders a button CTA when the action has an onClick", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <EmptyPanel
        title="No agents match"
        detail="Try removing a filter."
        action={{ label: "Reset filters", onClick }}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Reset filters" }));

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("renders without a CTA when no action is provided", () => {
    render(<EmptyPanel title="No audit events" detail="Events appear here as agents act." />);

    expect(screen.getByText("No audit events")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
