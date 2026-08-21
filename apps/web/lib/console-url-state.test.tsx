import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  enumUrlField,
  opaqueStringUrlField,
  stringUrlField,
  useConsoleUrlState,
} from "./console-url-state";

const schema = {
  itemId: stringUrlField("item_id"),
  tab: enumUrlField("tab", ["overview", "evidence"] as const, "overview"),
};

function Fixture() {
  const [state, setState] = useConsoleUrlState(schema);

  return (
    <div>
      <output>{`${state.itemId}:${state.tab}`}</output>
      <button onClick={() => setState({ itemId: "item_2" })} type="button">Select</button>
      <button
        onClick={() => setState({ itemId: "item_3" }, { history: "push" })}
        type="button"
      >
        Traverse
      </button>
      <button onClick={() => setState({ itemId: "", tab: "overview" })} type="button">
        Reset
      </button>
    </div>
  );
}

const opaqueSchema = {
  nodeId: opaqueStringUrlField("node_id"),
};

const opaqueNodeId = " node/with?# ";

function OpaqueIdFixture() {
  const [state, setState] = useConsoleUrlState(opaqueSchema);

  return (
    <div>
      <output aria-label="Opaque node id">{state.nodeId}</output>
      <button onClick={() => setState({ nodeId: opaqueNodeId })} type="button">
        Select opaque id
      </button>
    </div>
  );
}

beforeEach(() => {
  window.history.replaceState(null, "", "/console");
});

describe("useConsoleUrlState", () => {
  it("restores valid state and degrades invalid enum values to the default", () => {
    window.history.replaceState(null, "", "/console?item_id=item_1&tab=unknown");
    render(<Fixture />);

    expect(screen.getByText("item_1:overview")).toBeInTheDocument();
  });

  it("uses replace semantics and omits default values from the URL", async () => {
    const user = userEvent.setup();
    const initialHistoryLength = window.history.length;
    render(<Fixture />);

    await user.click(screen.getByRole("button", { name: "Select" }));
    expect(window.location.search).toBe("?item_id=item_2");
    expect(window.history.length).toBe(initialHistoryLength);

    await user.click(screen.getByRole("button", { name: "Reset" }));
    expect(window.location.search).toBe("");
    expect(window.history.length).toBe(initialHistoryLength);
  });

  it("can push traversable record state into browser history", async () => {
    const user = userEvent.setup();
    const pushState = vi.spyOn(window.history, "pushState");
    render(<Fixture />);

    await user.click(screen.getByRole("button", { name: "Traverse" }));

    expect(window.location.search).toBe("?item_id=item_3");
    expect(pushState).toHaveBeenCalledWith(
      window.history.state,
      "",
      "/console?item_id=item_3",
    );
  });

  it("round-trips opaque identifiers without trimming or treating path characters as URL syntax", async () => {
    window.history.replaceState(
      null,
      "",
      `/console?node_id=${encodeURIComponent(opaqueNodeId)}`,
    );
    const { unmount } = render(<OpaqueIdFixture />);

    expect(screen.getByLabelText("Opaque node id").textContent).toBe(opaqueNodeId);

    unmount();
    window.history.replaceState(null, "", "/console");
    render(<OpaqueIdFixture />);
    await userEvent.click(screen.getByRole("button", { name: "Select opaque id" }));

    expect(new URLSearchParams(window.location.search).get("node_id")).toBe(opaqueNodeId);
    expect(window.location.hash).toBe("");
  });
});
