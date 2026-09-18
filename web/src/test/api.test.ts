import { afterEach, describe, expect, it, vi } from "vitest";
import { AnalysisRequestError, analyzeCueFile } from "../api";

const okReport = {
  status: "ok",
  channels_checked: 2,
  conflict_count: 1,
  conflicts: [
    { channel: 1, cue_a: "A", cue_b: "B", overlap_start_ms: 50, overlap_end_ms: 100 },
  ],
  contention_windows: [
    { channel: 1, start_ms: 50, end_ms: 100, conflict_count: 1 },
  ],
};

function jsonResponse(status: number, body: unknown): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: () => Promise.resolve(body),
  } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("analyzeCueFile", () => {
  it("把原始文本 POST 给真实 API 并返回解析后的报告", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, okReport));
    vi.stubGlobal("fetch", fetchMock);

    const report = await analyzeCueFile('[{"cue":"A"}]');

    expect(report).toEqual(okReport);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/analyze");
    expect(init.method).toBe("POST");
    expect(init.body).toBe('[{"cue":"A"}]');
    expect((init.headers as Record<string, string>)["Content-Type"]).toContain(
      "application/json",
    );
  });

  it("422 时抛出携带数组下标的 AnalysisRequestError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(422, {
          detail: {
            message: "cue 文件校验失败",
            errors: [{ index: 2, message: "channel 必须在 1～512 之间" }],
          },
        }),
      ),
    );

    const promise = analyzeCueFile("bad");
    await expect(promise).rejects.toBeInstanceOf(AnalysisRequestError);
    await expect(promise).rejects.toMatchObject({
      detail: {
        message: "cue 文件校验失败",
        errors: [{ index: 2, message: "channel 必须在 1～512 之间" }],
      },
    });
  });

  it("网络不可达时抛出友好错误", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    await expect(analyzeCueFile("x")).rejects.toMatchObject({
      detail: { message: expect.stringContaining("无法连接") },
    });
  });

  it("非 422 的异常状态码抛出带状态码的错误", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(500, {})));
    await expect(analyzeCueFile("x")).rejects.toMatchObject({
      detail: { message: expect.stringContaining("500") },
    });
  });

  it("422 但响应体异常时也能给出错误对象", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(422, null)));
    await expect(analyzeCueFile("x")).rejects.toBeInstanceOf(AnalysisRequestError);
  });
});
