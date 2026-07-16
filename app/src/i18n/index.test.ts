import { expect, test } from "vitest";
import { t } from "./index";

test("t returns traditional chinese copy", () => {
  expect(t("conn.unavailable")).toBe("無法連線到核心服務");
});
