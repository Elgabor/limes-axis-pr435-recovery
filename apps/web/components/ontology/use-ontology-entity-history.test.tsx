import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useCallback } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { opaqueStringUrlField, useConsoleUrlState } from "@/lib/console-url-state";

import { useOntologyEntityHistory } from "./use-ontology-entity-history";

const schema = {
  entityId: opaqueStringUrlField("entity_id"),
};

function Fixture() {
  const [urlState, setUrlState] = useConsoleUrlState(schema);
  const entityId = urlState.entityId || null;
  const updateEntityId = useCallback(
    (nextEntityId: string, history: "push" | "replace") => {
      setUrlState({ entityId: nextEntityId }, { history });
    },
    [setUrlState],
  );
  const { closeEntity, navigateToEntity } = useOntologyEntityHistory({
    entityId,
    updateEntityId,
  });

  return (
    <div>
      <output aria-label="Selected entity">{entityId ?? "closed"}</output>
      <button onClick={() => navigateToEntity("asset_a")} type="button">
        Open A
      </button>
      <button onClick={() => navigateToEntity("asset_b")} type="button">
        Open B
      </button>
      <button onClick={closeEntity} type="button">
        Close
      </button>
    </div>
  );
}

beforeEach(() => {
  window.history.replaceState(null, "", "/ontology");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useOntologyEntityHistory", () => {
  it("collapses every in-app entity traversal entry on explicit close", async () => {
    const user = userEvent.setup();
    const go = vi.spyOn(window.history, "go").mockImplementation(() => undefined);
    render(<Fixture />);

    await user.click(screen.getByRole("button", { name: "Open A" }));
    await user.click(screen.getByRole("button", { name: "Open B" }));
    expect(new URLSearchParams(window.location.search).get("entity_id")).toBe("asset_b");

    await user.click(screen.getByRole("button", { name: "Close" }));

    expect(go).toHaveBeenCalledOnce();
    expect(go).toHaveBeenCalledWith(-2);
  });

  it("uses replace semantics when a directly linked entity closes", async () => {
    window.history.replaceState(null, "", "/ontology?entity_id=asset_a");
    const user = userEvent.setup();
    const go = vi.spyOn(window.history, "go");
    const replaceState = vi.spyOn(window.history, "replaceState");
    render(<Fixture />);

    await user.click(screen.getByRole("button", { name: "Close" }));

    expect(go).not.toHaveBeenCalled();
    expect(replaceState).toHaveBeenCalledWith(window.history.state, "", "/ontology");
    expect(screen.getByLabelText("Selected entity")).toHaveTextContent("closed");
    expect(window.location.search).toBe("");
  });

  it("restores traversal depth after Back before closing", async () => {
    const user = userEvent.setup();
    render(<Fixture />);

    await user.click(screen.getByRole("button", { name: "Open A" }));
    await user.click(screen.getByRole("button", { name: "Open B" }));
    await act(async () => {
      window.history.back();
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });
    await waitFor(() => {
      expect(screen.getByLabelText("Selected entity")).toHaveTextContent("asset_a");
    });

    const go = vi.spyOn(window.history, "go").mockImplementation(() => undefined);
    await user.click(screen.getByRole("button", { name: "Close" }));

    expect(go).toHaveBeenCalledWith(-1);
  });
});
