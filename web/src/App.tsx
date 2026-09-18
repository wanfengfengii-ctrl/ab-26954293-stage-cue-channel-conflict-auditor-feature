import { useCallback, useState } from "react";
import { AnalysisRequestError, analyzeCueFile } from "./api";
import { ConflictReport } from "./components/ConflictReport";
import { ErrorReport } from "./components/ErrorReport";
import type { AnalysisErrorDetail, AnalysisReport } from "./types";

type AppState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "report"; report: AnalysisReport }
  | { kind: "error"; error: AnalysisErrorDetail };

export default function App() {
  const [state, setState] = useState<AppState>({ kind: "idle" });
  const [fileName, setFileName] = useState<string | null>(null);
  const [analysisSeq, setAnalysisSeq] = useState(0);

  const handleFile = useCallback(async (file: File) => {
    setFileName(file.name);
    // 每次分析都先清空旧结果，避免新旧报告混显
    setState({ kind: "loading" });

    let text: string;
    try {
      text = await file.text();
    } catch {
      setState({
        kind: "error",
        error: { message: "无法读取文件内容，请确认是 UTF-8 文本文件", errors: [] },
      });
      return;
    }

    try {
      const report = await analyzeCueFile(text);
      setAnalysisSeq((seq) => seq + 1);
      setState({ kind: "report", report });
    } catch (err) {
      const error: AnalysisErrorDetail =
        err instanceof AnalysisRequestError
          ? err.detail
          : { message: "发生未知错误", errors: [] };
      // 校验失败：清除旧报告，只展示错误
      setState({ kind: "error", error });
    }
  }, []);

  return (
    <main className="page">
      <header>
        <h1>灯光 Cue 冲突检查</h1>
        <p className="subtitle">
          上传灯光部门导出的 UTF-8 JSON cue 文件，检查同一 DMX 通道上是否存在两两重叠的渐变区间。
        </p>
      </header>

      <section className="upload-panel">
        <label htmlFor="cue-file" className="file-label">
          选择 cue 文件（.json，UTF-8）
        </label>
        <input
          id="cue-file"
          data-testid="file-input"
          type="file"
          accept=".json,application/json"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) {
              void handleFile(file);
            }
            // 允许重复选择同一文件重新分析
            event.target.value = "";
          }}
        />
        {fileName && <p className="file-name">当前文件：{fileName}</p>}
      </section>

      {state.kind === "loading" && (
        <p data-testid="loading" className="loading">
          分析中…
        </p>
      )}
      {state.kind === "error" && <ErrorReport error={state.error} />}
      {state.kind === "report" && (
        <ConflictReport key={analysisSeq} report={state.report} />
      )}
    </main>
  );
}
