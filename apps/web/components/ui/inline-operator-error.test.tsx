import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InlineOperatorError } from "./inline-operator-error";

describe("InlineOperatorError", () => {
  it("shows safe operator copy and its request reference", () => {
    render(
      <InlineOperatorError
        error={{
          code: "WRITE_FAILED",
          reason: null,
          message: "The policy could not be saved.",
          requestId: "request-policy-503",
          status: 503,
        }}
        prefix="Policy authoring failed"
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Policy authoring failed: The policy could not be saved.",
    );
    expect(screen.getByText("request-policy-503")).toBeInTheDocument();
  });

  it("omits a reference for semantic failures", () => {
    render(
      <InlineOperatorError
        error={{
          code: null,
          reason: null,
          message: "Fix the highlighted fields; nothing was sent.",
          requestId: null,
          status: null,
        }}
      />,
    );

    expect(screen.queryByText(/Request reference/)).not.toBeInTheDocument();
  });
});
