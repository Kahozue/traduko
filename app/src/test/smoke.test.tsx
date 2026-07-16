import { render } from "@testing-library/react";
import { test } from "vitest";
import App from "../App";

test("app renders without crashing", () => {
  render(<App />);
});
