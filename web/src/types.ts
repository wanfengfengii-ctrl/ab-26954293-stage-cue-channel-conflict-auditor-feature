export interface Conflict {
  channel: number;
  cue_a: string;
  cue_b: string;
  overlap_start_ms: number;
  overlap_end_ms: number;
}

export interface ContentionWindow {
  channel: number;
  start_ms: number;
  end_ms: number;
  conflict_count: number;
}

export interface IsolationItem {
  /** 源数组下标 */
  index: number;
  cue: string;
  channel: number;
  start_ms: number;
  end_ms: number;
}

export interface AnalysisReport {
  status: "ok";
  channels_checked: number;
  conflict_count: number;
  conflicts: Conflict[];
  contention_windows: ContentionWindow[];
  isolation_plan: IsolationItem[];
}

export interface AnalysisErrorItem {
  /** 数组下标；整份 JSON 非法时为 null */
  index: number | null;
  message: string;
}

export interface AnalysisErrorDetail {
  message: string;
  errors: AnalysisErrorItem[];
}
