import { useMemo, useState } from "react";
import type {
  AnalysisReport,
  ContentionWindow,
  IsolationItem,
} from "../types";

function windowKey(window: ContentionWindow): string {
  return `${window.channel}:${window.start_ms}:${window.end_ms}`;
}

/** 半开区间相交判定：[cs, ce) 与 [ws, we) 有公共毫秒才算相交 */
function intersectsWindow(
  conflict: AnalysisReport["conflicts"][number],
  window: ContentionWindow,
): boolean {
  return (
    conflict.channel === window.channel &&
    conflict.overlap_start_ms < window.end_ms &&
    conflict.overlap_end_ms > window.start_ms
  );
}

export function ConflictReport({ report }: { report: AnalysisReport }) {
  const [channelFilter, setChannelFilter] = useState<"all" | number>("all");
  const [selectedWindowKey, setSelectedWindowKey] = useState<string | null>(null);

  const conflictChannels = useMemo(
    () => [...new Set(report.conflicts.map((c) => c.channel))].sort((a, b) => a - b),
    [report],
  );

  // 建议隔离项后端已按通道 → 源下标排序；通道筛选同步约束该方案。
  // 按通道分组，保持原有顺序，供报告逐通道展示。
  const isolationByChannel = useMemo(() => {
    const groups = new Map<number, IsolationItem[]>();
    for (const item of report.isolation_plan) {
      if (channelFilter !== "all" && item.channel !== channelFilter) {
        continue;
      }
      const list = groups.get(item.channel);
      if (list) {
        list.push(item);
      } else {
        groups.set(item.channel, [item]);
      }
    }
    return [...groups.entries()].sort((a, b) => a[0] - b[0]);
  }, [report, channelFilter]);

  if (report.conflicts.length === 0) {
    return (
      <section data-testid="report-panel" className="report">
        <p data-testid="status-banner" className="banner ok">
          ✅ 可放行：未检测到通道冲突。本次共检查 {report.channels_checked} 个通道。
        </p>
      </section>
    );
  }

  const visibleWindows =
    channelFilter === "all"
      ? report.contention_windows
      : report.contention_windows.filter((w) => w.channel === channelFilter);

  const selectedWindow =
    report.contention_windows.find((w) => windowKey(w) === selectedWindowKey) ?? null;

  const channelVisible =
    channelFilter === "all"
      ? report.conflicts
      : report.conflicts.filter((c) => c.channel === channelFilter);

  const visible = selectedWindow
    ? channelVisible.filter((c) => intersectsWindow(c, selectedWindow))
    : channelVisible;

  return (
    <section data-testid="report-panel" className="report">
      <p data-testid="status-banner" className="banner warn">
        ⚠️ 检测到 {report.conflict_count} 处通道冲突（共检查 {report.channels_checked}{" "}
        个通道），请退回灯光部门修改。
      </p>

      <div className="filter-row">
        <label htmlFor="channel-filter">按通道筛选：</label>
        <select
          id="channel-filter"
          data-testid="channel-filter"
          value={channelFilter}
          onChange={(event) => {
            // 切换通道时清除时间窗选择，避免选中窗与新通道组合出空结果
            setSelectedWindowKey(null);
            setChannelFilter(
              event.target.value === "all" ? "all" : Number(event.target.value),
            );
          }}
        >
          <option value="all">全部通道</option>
          {conflictChannels.map((channel) => (
            <option key={channel} value={channel}>
              通道 {channel}
            </option>
          ))}
        </select>
      </div>

      {isolationByChannel.length > 0 && (
        <div className="isolation-panel" data-testid="isolation-panel">
          <p className="isolation-title">
            建议临时隔离（全局最少项数；隔离后保留指令可完整走台）：
          </p>
          {isolationByChannel.map(([channel, items]) => (
            <div key={channel} className="isolation-channel" data-testid="isolation-channel">
              <p className="isolation-channel-title">通道 {channel}</p>
              <ul className="isolation-list">
                {items.map((item) => (
                  <li
                    key={`${item.channel}-${item.source_index}`}
                    data-testid="isolation-item"
                  >
                    <span className="isolation-index">下标 {item.source_index}</span>
                    <span className="isolation-name">{item.cue}</span>
                    <span className="isolation-range">
                      [{item.start_ms}, {item.end_ms}) ms
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      {visibleWindows.length > 0 && (
        <div className="window-panel">
          <p className="window-title">抢值时段（点击定位冲突，再次点击恢复全部明细）：</p>
          <ul className="window-list">
            {visibleWindows.map((window) => {
              const key = windowKey(window);
              const active = key === selectedWindowKey;
              return (
                <li key={key}>
                  <button
                    type="button"
                    data-testid="contention-window"
                    aria-pressed={active}
                    className={active ? "window-chip active" : "window-chip"}
                    onClick={() => setSelectedWindowKey(active ? null : key)}
                  >
                    通道 {window.channel} · [{window.start_ms}, {window.end_ms}) ms ·{" "}
                    {window.conflict_count} 处冲突
                  </button>
                </li>
              );
            })}
          </ul>
          {selectedWindow && (
            <p data-testid="window-filter-note" className="window-note">
              仅显示与所选时段相交的冲突，再次点击该时段恢复当前通道的全部明细。
            </p>
          )}
        </div>
      )}

      <table className="conflict-table">
        <thead>
          <tr>
            <th>通道</th>
            <th>Cue A</th>
            <th>Cue B</th>
            <th>重叠区间 [start, end)（ms）</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((conflict, index) => (
            <tr
              key={`${conflict.channel}-${conflict.overlap_start_ms}-${conflict.overlap_end_ms}-${conflict.cue_a}-${conflict.cue_b}-${index}`}
              data-testid="conflict-row"
            >
              <td>{conflict.channel}</td>
              <td>{conflict.cue_a}</td>
              <td>{conflict.cue_b}</td>
              <td>
                [{conflict.overlap_start_ms}, {conflict.overlap_end_ms})
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {visible.length === 0 && <p className="empty-note">所选通道没有冲突。</p>}
    </section>
  );
}
