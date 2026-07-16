import { expect, test } from "vitest";
import { t } from "./index";

test("t returns traditional chinese copy", () => {
  expect(t("conn.unavailable")).toBe("核心服務啟動失敗");
});
