import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { SyncConfigDoc, SyncStatus } from "../../lib/api/types";
import { SyncSection } from "./SyncSection";

const BASE: SyncConfigDoc = {
  enabled: false,
  mode: "folder",
  folder_path: "",
  webdav_url: "",
  webdav_username: "",
  webdav_password: "",
  auto_interval_minutes: 0,
};

const EMPTY_STATUS: SyncStatus = {
  enabled: false,
  mode: "folder",
  syncing: false,
  last_sync: null,
  last_result: null,
  conflicts: [],
  peers: [],
};

function setup(
  sync: SyncConfigDoc = BASE,
  status: SyncStatus = EMPTY_STATUS,
  handlers: {
    onSyncNow?: () => void;
    onResolve?: (file: string, source: string, choice: "local" | "remote") => void;
  } = {},
) {
  const onChange = vi.fn();
  render(
    <SyncSection
      sync={sync}
      status={status}
      onChange={onChange}
      onSyncNow={handlers.onSyncNow ?? (() => {})}
      onResolve={handlers.onResolve ?? (() => {})}
    />,
  );
  return { onChange };
}

test("enabling folder sync with an empty path invalidates the section", async () => {
  const { onChange } = setup();
  await userEvent.click(screen.getByLabelText("啟用雲端同步"));
  expect(onChange).toHaveBeenLastCalledWith(null);
  expect(screen.getByText("資料夾路徑不可空白")).toBeInTheDocument();
});

test("valid folder config propagates the updated doc", async () => {
  const { onChange } = setup({ ...BASE, enabled: true });
  await userEvent.type(screen.getByLabelText("資料夾路徑"), "/tmp/cloud");
  expect(onChange).toHaveBeenLastCalledWith({
    ...BASE,
    enabled: true,
    folder_path: "/tmp/cloud",
  });
});

test("webdav mode reveals the url and credential fields", async () => {
  setup({ ...BASE, mode: "webdav" });
  expect(screen.getByLabelText("WebDAV 網址")).toBeInTheDocument();
  expect(screen.getByLabelText("WebDAV 帳號")).toBeInTheDocument();
});

test("sync now button triggers the handler", async () => {
  const onSyncNow = vi.fn();
  setup({ ...BASE, enabled: true, folder_path: "/tmp/cloud" }, EMPTY_STATUS, {
    onSyncNow,
  });
  await userEvent.click(screen.getByRole("button", { name: "立即同步" }));
  expect(onSyncNow).toHaveBeenCalled();
});

test("conflicts render both values and resolve", async () => {
  const onResolve = vi.fn();
  const status: SyncStatus = {
    ...EMPTY_STATUS,
    conflicts: [
      {
        file: "glossaries/global.csv",
        source: "term",
        local: { source: "term", target: "mine", notes: "", scope: "" },
        remote: { source: "term", target: "theirs", notes: "", scope: "" },
      },
    ],
  };
  setup(BASE, status, { onResolve });
  expect(screen.getByText("mine")).toBeInTheDocument();
  expect(screen.getByText("theirs")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "採用遠端" }));
  expect(onResolve).toHaveBeenCalledWith("glossaries/global.csv", "term", "remote");
});

test("peer machines and their tasks are listed read-only", () => {
  const status: SyncStatus = {
    ...EMPTY_STATUS,
    peers: [
      {
        machine: "laptop-ab12",
        tasks: [
          {
            id: "t1",
            project: "p",
            name: "ep01",
            status: "completed",
            profile: "x",
            created_at: "",
            updated_at: "",
          },
        ],
      },
    ],
  };
  setup(BASE, status);
  expect(screen.getByText("laptop-ab12")).toBeInTheDocument();
  expect(screen.getByText(/ep01/)).toBeInTheDocument();
  expect(screen.getByText(/已完成/)).toBeInTheDocument();
});
