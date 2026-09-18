import type { AnalysisErrorDetail, AnalysisReport } from "./types";

/** 同源部署时为空字符串（由 nginx / Vite 代理 /api），也可用 VITE_API_BASE 指定绝对地址 */
const API_BASE: string = import.meta.env.VITE_API_BASE ?? "";

export class AnalysisRequestError extends Error {
  readonly detail: AnalysisErrorDetail;

  constructor(detail: AnalysisErrorDetail) {
    super(detail.message);
    this.name = "AnalysisRequestError";
    this.detail = detail;
  }
}

function normalizeDetail(raw: unknown): AnalysisErrorDetail {
  if (raw && typeof raw === "object") {
    const candidate = raw as Record<string, unknown>;
    if (typeof candidate.message === "string" && Array.isArray(candidate.errors)) {
      const errors = candidate.errors
        .filter(
          (item): item is { index?: unknown; message: string } =>
            !!item && typeof item === "object" && typeof (item as { message?: unknown }).message === "string",
        )
        .map((item) => ({
          index: typeof item.index === "number" ? item.index : null,
          message: item.message,
        }));
      return { message: candidate.message, errors };
    }
  }
  return { message: "分析服务返回了无法识别的错误内容", errors: [] };
}

/** 把原始 JSON 文本交给真实 API 校验与分析；422 时抛出携带下标信息的 AnalysisRequestError */
export async function analyzeCueFile(fileText: string): Promise<AnalysisReport> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: fileText,
    });
  } catch {
    throw new AnalysisRequestError({
      message: "无法连接分析服务，请确认 API 已启动",
      errors: [],
    });
  }

  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (response.status === 422) {
    const detail =
      body && typeof body === "object" && "detail" in body
        ? (body as { detail: unknown }).detail
        : null;
    throw new AnalysisRequestError(normalizeDetail(detail));
  }
  if (!response.ok) {
    throw new AnalysisRequestError({
      message: `分析服务异常（HTTP ${response.status}）`,
      errors: [],
    });
  }
  return body as AnalysisReport;
}
