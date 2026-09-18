import type { AnalysisErrorDetail } from "../types";

export function ErrorReport({ error }: { error: AnalysisErrorDetail }) {
  return (
    <section data-testid="error-panel" className="report">
      <p className="banner error">❌ 文件校验失败：{error.message}</p>
      {error.errors.length > 0 && (
        <ul className="error-list">
          {error.errors.map((item, index) => (
            <li key={index} data-testid="error-item">
              <span className="error-index">
                {item.index === null ? "整体" : `数组下标 ${item.index}`}
              </span>
              ：{item.message}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
