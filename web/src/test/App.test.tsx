import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";

const conflictReport = {
  status: "ok",
  channels_checked: 3,
  conflict_count: 2,
  conflicts: [
    { channel: 1, cue_a: "开场", cue_b: "追光", overlap_start_ms: 500, overlap_end_ms: 1000 },
    { channel: 2, cue_a: "面光", cue_b: "侧光", overlap_start_ms: 100, overlap_end_ms: 200 },
  ],
  contention_windows: [
    { channel: 1, start_ms: 500, end_ms: 1000, conflict_count: 1 },
    { channel: 2, start_ms: 100, end_ms: 200, conflict_count: 1 },
  ],
};

// 通道 1 上三条冲突链式合并为 [200, 1000)，另有一条独立冲突 [1100, 1200)；
// 通道 2 一条独立冲突 [200, 400)
const windowReport = {
  status: "ok",
  channels_checked: 2,
  conflict_count: 5,
  conflicts: [
    { channel: 1, cue_a: "底光", cue_b: "染色", overlap_start_ms: 200, overlap_end_ms: 600 },
    { channel: 1, cue_a: "染色", cue_b: "追光", overlap_start_ms: 500, overlap_end_ms: 600 },
    { channel: 1, cue_a: "底光", cue_b: "追光", overlap_start_ms: 500, overlap_end_ms: 1000 },
    { channel: 1, cue_a: "追光", cue_b: "频闪", overlap_start_ms: 1100, overlap_end_ms: 1200 },
    { channel: 2, cue_a: "侧光", cue_b: "面光", overlap_start_ms: 200, overlap_end_ms: 400 },
  ],
  contention_windows: [
    { channel: 1, start_ms: 200, end_ms: 1000, conflict_count: 3 },
    { channel: 1, start_ms: 1100, end_ms: 1200, conflict_count: 1 },
    { channel: 2, start_ms: 200, end_ms: 400, conflict_count: 1 },
  ],
};

const cleanReport = {
  status: "ok",
  channels_checked: 4,
  conflict_count: 0,
  conflicts: [],
  contention_windows: [],
};

function jsonResponse(status: number, body: unknown): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: () => Promise.resolve(body),
  } as Response;
}

function uploadFile(content: string, name = "cues.json") {
  const input = screen.getByTestId("file-input") as HTMLInputElement;
  const file = new File([content], name, { type: "application/json" });
  fireEvent.change(input, { target: { files: [file] } });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("展示冲突列表并可按通道筛选", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, conflictReport)));
    render(<App />);
    uploadFile("[]");

    const rows = await screen.findAllByTestId("conflict-row");
    expect(rows).toHaveLength(2);
    expect(screen.getByTestId("status-banner")).toHaveTextContent("2 处通道冲突");
    expect(screen.getByTestId("status-banner")).toHaveTextContent("共检查 3 个通道");
    expect(rows[0]).toHaveTextContent("[500, 1000)");

    fireEvent.change(screen.getByTestId("channel-filter"), { target: { value: "2" } });
    const filtered = screen.getAllByTestId("conflict-row");
    expect(filtered).toHaveLength(1);
    expect(filtered[0]).toHaveTextContent("面光");
    expect(filtered[0]).toHaveTextContent("[100, 200)");

    fireEvent.change(screen.getByTestId("channel-filter"), { target: { value: "all" } });
    expect(screen.getAllByTestId("conflict-row")).toHaveLength(2);
  });

  it("无冲突时显示可放行与检查通道数，且不出现时间窗", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, cleanReport)));
    render(<App />);
    uploadFile("[]");

    const banner = await screen.findByTestId("status-banner");
    expect(banner).toHaveTextContent("可放行");
    expect(banner).toHaveTextContent("4 个通道");
    expect(screen.queryByTestId("channel-filter")).not.toBeInTheDocument();
    expect(screen.queryByTestId("conflict-row")).not.toBeInTheDocument();
    expect(screen.queryByTestId("contention-window")).not.toBeInTheDocument();
  });

  it("展示抢值时间窗，点击下钻相交冲突，再次点击恢复全部明细", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, windowReport)));
    render(<App />);
    uploadFile("[]");

    const windows = await screen.findAllByTestId("contention-window");
    expect(windows).toHaveLength(3);
    expect(windows[0]).toHaveTextContent("通道 1");
    expect(windows[0]).toHaveTextContent("[200, 1000)");
    expect(windows[0]).toHaveTextContent("3 处冲突");
    expect(screen.getAllByTestId("conflict-row")).toHaveLength(5);

    // 点击链式合并窗口：只剩与该窗相交的 3 条通道 1 冲突
    fireEvent.click(windows[0]);
    const drilled = screen.getAllByTestId("conflict-row");
    expect(drilled).toHaveLength(3);
    expect(drilled[0]).toHaveTextContent("染色");
    expect(drilled[1]).toHaveTextContent("追光");
    expect(drilled[2]).toHaveTextContent("[500, 1000)");
    expect(screen.getByTestId("window-filter-note")).toBeInTheDocument();

    // 再次点击同一窗口：恢复全部明细
    fireEvent.click(screen.getAllByTestId("contention-window")[0]);
    expect(screen.getAllByTestId("conflict-row")).toHaveLength(5);
    expect(screen.queryByTestId("window-filter-note")).not.toBeInTheDocument();

    // 点击独立窗口：只剩端点相接之外的 1 条冲突
    fireEvent.click(screen.getAllByTestId("contention-window")[1]);
    const single = screen.getAllByTestId("conflict-row");
    expect(single).toHaveLength(1);
    expect(single[0]).toHaveTextContent("[1100, 1200)");
  });

  it("时间窗随通道筛选联动，切换通道时清除选择", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(200, windowReport)));
    render(<App />);
    uploadFile("[]");

    await screen.findAllByTestId("contention-window");
    // 筛选通道 2：只剩该通道的时间窗与冲突
    fireEvent.change(screen.getByTestId("channel-filter"), { target: { value: "2" } });
    const channelWindows = screen.getAllByTestId("contention-window");
    expect(channelWindows).toHaveLength(1);
    expect(channelWindows[0]).toHaveTextContent("通道 2");

    // 选中该窗口后切回全部通道：选择被清除，恢复全部明细
    fireEvent.click(channelWindows[0]);
    expect(screen.getAllByTestId("conflict-row")).toHaveLength(1);
    fireEvent.change(screen.getByTestId("channel-filter"), { target: { value: "all" } });
    expect(screen.getAllByTestId("conflict-row")).toHaveLength(5);
    expect(screen.queryByTestId("window-filter-note")).not.toBeInTheDocument();
  });

  it("上传新文件后时间窗选择被清除", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, windowReport));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    uploadFile("first");
    const windows = await screen.findAllByTestId("contention-window");
    fireEvent.click(windows[0]);
    expect(screen.getAllByTestId("conflict-row")).toHaveLength(3);

    // 再次上传（即使是同一份报告）：新报告整体替换，选择不保留
    uploadFile("second");
    const windowsAgain = await screen.findAllByTestId("contention-window");
    expect(windowsAgain).toHaveLength(3);
    expect(screen.getAllByTestId("conflict-row")).toHaveLength(5);
    expect(screen.queryByTestId("window-filter-note")).not.toBeInTheDocument();
  });

  it("422 时清除旧报告与时间窗并标明数组下标", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, conflictReport))
      .mockResolvedValueOnce(
        jsonResponse(422, {
          detail: {
            message: "cue 文件校验失败",
            errors: [
              { index: 1, message: "channel 必须在 1～512 之间" },
              { index: 3, message: "end_ms 必须大于 start_ms" },
            ],
          },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    uploadFile("good");
    await screen.findAllByTestId("conflict-row");
    expect(screen.getAllByTestId("contention-window")).toHaveLength(2);

    uploadFile("bad");
    const items = await screen.findAllByTestId("error-item");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("数组下标 1");
    expect(items[0]).toHaveTextContent("channel 必须在 1～512 之间");
    expect(items[1]).toHaveTextContent("数组下标 3");
    // 旧报告与时间窗已被清除
    expect(screen.queryByTestId("conflict-row")).not.toBeInTheDocument();
    expect(screen.queryByTestId("contention-window")).not.toBeInTheDocument();
    expect(screen.queryByTestId("status-banner")).not.toBeInTheDocument();
  });

  it("整份 JSON 非法时错误不携带下标", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(422, {
          detail: {
            message: "JSON 解析失败",
            errors: [{ index: null, message: "JSON 语法错误: ..." }],
          },
        }),
      ),
    );
    render(<App />);
    uploadFile("{oops");

    const item = await screen.findByTestId("error-item");
    expect(item).toHaveTextContent("整体");
    expect(item).toHaveTextContent("JSON 语法错误");
  });

  it("校验失败后再次上传合法文件可恢复显示报告与时间窗", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(422, {
          detail: {
            message: "cue 文件校验失败",
            errors: [{ index: 0, message: "channel 必须是整数" }],
          },
        }),
      )
      .mockResolvedValueOnce(jsonResponse(200, windowReport));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    uploadFile("bad");
    await screen.findByTestId("error-panel");

    uploadFile("good");
    const windows = await screen.findAllByTestId("contention-window");
    expect(windows).toHaveLength(3);
    expect(screen.queryByTestId("error-panel")).not.toBeInTheDocument();

    // 恢复后时间窗可正常下钻
    fireEvent.click(windows[0]);
    expect(screen.getAllByTestId("conflict-row")).toHaveLength(3);
  });
});
