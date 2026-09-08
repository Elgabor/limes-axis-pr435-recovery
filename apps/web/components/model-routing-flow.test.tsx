import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { groupRoutingDependencies, ModelRoutingFlow } from "./model-routing-flow";

const routes = [
  { provider_id: "local", provider_name: "Local inference", model: "quality-model" },
  { provider_id: "local", provider_name: "Local inference", model: "quality-model" },
  { provider_id: "local", provider_name: "Local inference", model: "planning-model" },
  { provider_id: "remote", provider_name: "Remote inference", model: "quality-model" },
];

describe("Model routing dependencies", () => {
  it("counts routes per provider/model pair without merging equal model or provider names", () => {
    const result = groupRoutingDependencies(routes.map((route) => ({ ...route, provider_name: "Shared name" })));
    expect(result).toEqual([
      { id: "local", name: "Shared name", count: 3, models: [{ name: "quality-model", count: 2 }, { name: "planning-model", count: 1 }] },
      { id: "remote", name: "Shared name", count: 1, models: [{ name: "quality-model", count: 1 }] },
    ]);
    expect(result.reduce((count, group) => count + group.count, 0)).toBe(routes.length);
  });

  it("exposes every count without hover and labels reference configuration honestly", () => {
    render(<ModelRoutingFlow routes={routes} sourceState="reference" />);
    expect(screen.getByText("4 configured routes · 2 providers")).toBeInTheDocument();
    expect(screen.getByText("model routing: reference scenario")).toBeInTheDocument();
    expect(screen.getByText("Includes blocked routes. Width = configured routes.")).toBeInTheDocument();
    const list = screen.getByLabelText("Routes by provider and model");
    expect(within(list).getByText("3 routes")).toBeInTheDocument();
    expect(within(list).getByText("2 routes")).toBeInTheDocument();
    expect(within(list).getAllByText("quality-model")).toHaveLength(2);
  });

  it("keeps missing names explicit and retains stale provenance", () => {
    render(<ModelRoutingFlow routes={[{ provider_id: "", provider_name: "", model: "" }]} sourceState="stale" />);
    const list = screen.getByLabelText("Routes by provider and model");
    expect(within(list).getByText("Unknown provider")).toBeInTheDocument();
    expect(within(list).getByText("Unknown model")).toBeInTheDocument();
    expect(screen.getByText("model routing: stale")).toBeInTheDocument();
    expect(screen.queryByText("model routing: live")).not.toBeInTheDocument();
  });

  it("shows an empty state without drawing invented dependencies", () => {
    render(<ModelRoutingFlow routes={[]} sourceState="empty" />);
    expect(screen.getByText("No configured routes to compare.")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Provider to model diagram" })).not.toBeInTheDocument();
  });

  it("retains all names and counts in the list for a dense inventory", () => {
    const dense = Array.from({ length: 13 }, (_, index) => ({ ...routes[0], model: `full-enterprise-model-name-${index}` }));
    render(<ModelRoutingFlow routes={dense} sourceState="live" />);
    expect(screen.queryByRole("region", { name: "Provider to model diagram" })).not.toBeInTheDocument();
    expect(screen.getByText("13 routes")).toBeInTheDocument();
    expect(screen.getByText("full-enterprise-model-name-12")).toBeInTheDocument();
    expect(screen.getAllByText("1 route")).toHaveLength(13);
  });
  it("previews on hover, pins a model on click and inspects only on explicit request", async () => {
    const user = userEvent.setup();
    const onInspect = vi.fn();
    render(<ModelRoutingFlow routes={routes} sourceState="reference" onInspect={onInspect} />);
    const diagram = screen.getByRole("region", { name: "Provider to model diagram" });
    const provider = within(diagram).getByRole("button", { name: "Select provider Local inference" });
    await user.hover(provider);
    expect(screen.getByRole("status")).toHaveTextContent("Local inference · 3 routes configured");
    expect(screen.queryByRole("button", { name: "View provider routes" })).not.toBeInTheDocument();
    await user.unhover(provider);
    expect(screen.getByRole("status")).toHaveTextContent("Select a provider or model");

    const model = within(diagram).getByRole("button", { name: "Select quality-model from Local inference" });
    await user.click(model);
    await user.unhover(model);
    expect(model).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Local inference → quality-model · 2 routes configured");
    expect(onInspect).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Inspect first matching route" }));
    expect(onInspect).toHaveBeenCalledWith({ providerId: "local", model: "quality-model" });
    await user.click(screen.getByRole("button", { name: "Reset selection" }));
    expect(model).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("status")).toHaveTextContent("Select a provider or model");
  });

  it("supports keyboard selection and Escape in the full-name list", async () => {
    const user = userEvent.setup();
    render(<ModelRoutingFlow routes={routes} sourceState="reference" />);
    const list = screen.getByLabelText("Routes by provider and model");
    const provider = within(list).getByRole("button", { name: "Select provider Remote inference" });
    act(() => provider.focus());
    expect(screen.getByRole("status")).toHaveTextContent("Remote inference · 1 route configured");
    expect(provider).toHaveAttribute("aria-pressed", "false");
    await user.keyboard("{Enter}");
    expect(provider).toHaveAttribute("aria-pressed", "true");
    await user.keyboard("{Escape}");
    expect(provider).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("status")).toHaveTextContent("Select a provider or model");
  });

  it("does not retain a selection or inspect action after its source disappears", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<ModelRoutingFlow routes={routes} sourceState="live" onInspect={vi.fn()} />);
    const diagram = screen.getByRole("region", { name: "Provider to model diagram" });
    await user.click(within(diagram).getByRole("button", { name: "Select provider Local inference" }));
    rerender(<ModelRoutingFlow routes={[routes[3]]} sourceState="live" onInspect={vi.fn()} />);
    expect(screen.getByRole("status")).not.toHaveTextContent("Local inference");
    expect(screen.queryByRole("button", { name: "View provider routes" })).not.toBeInTheDocument();
  });

});
