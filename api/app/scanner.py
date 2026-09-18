"""DMX 通道冲突核心扫描逻辑。

区间统一采用左闭右开 [start_ms, end_ms)：
- 仅端点相接（一个的 end_ms 等于另一个的 start_ms）不算冲突；
- 重叠段取两个起点中的较大值到两个终点中的较小值。
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Cue:
    cue: str
    channel: int
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class Conflict:
    channel: int
    cue_a: str
    cue_b: str
    overlap_start_ms: int
    overlap_end_ms: int


@dataclass(frozen=True)
class ContentionWindow:
    """同一通道上一段连续抢值时段：由相交或首尾相接的冲突重叠区间合并而来。"""

    channel: int
    start_ms: int
    end_ms: int
    conflict_count: int


@dataclass(frozen=True)
class IsolationItem:
    """一条建议临时隔离的 cue：携带源数组下标、名称、通道与原始区间。"""

    index: int
    cue: str
    channel: int
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class ScanReport:
    channels_checked: int
    conflicts: list[Conflict] = field(default_factory=list)
    contention_windows: list[ContentionWindow] = field(default_factory=list)
    isolation_plan: list[IsolationItem] = field(default_factory=list)


def _time_order(cue: Cue) -> tuple[int, int, str]:
    """扫描顺序：必须按时间先后，扫描线提前终止才成立。"""
    return (cue.start_ms, cue.end_ms, cue.cue)


def _name_order(cue: Cue) -> tuple[str, int, int]:
    """同一冲突内两个 cue 的展示顺序：按名称字典序。"""
    return (cue.cue, cue.start_ms, cue.end_ms)


def scan_conflicts(cues: list[Cue]) -> ScanReport:
    """按通道找出全部两两重叠，返回确定排序的冲突列表。"""
    by_channel: dict[int, list[Cue]] = {}
    for cue in cues:
        by_channel.setdefault(cue.channel, []).append(cue)

    conflicts: list[Conflict] = []
    for channel, items in by_channel.items():
        # 必须按 start_ms 升序扫描：b.start_ms >= a.end_ms 时其后的 cue
        # 起点只会更晚，不可能再与 a 重叠，才能安全提前终止。
        # （若按名称排序，名称居中但时间很靠后的 cue 会触发提前终止，
        # 把名称靠后但实际重叠的 cue 跳过，导致漏判。）
        items.sort(key=_time_order)
        for i, a in enumerate(items):
            for b in items[i + 1 :]:
                if b.start_ms >= a.end_ms:
                    break
                overlap_start = max(a.start_ms, b.start_ms)
                overlap_end = min(a.end_ms, b.end_ms)
                if overlap_start >= overlap_end:
                    continue
                first, second = (a, b) if _name_order(a) <= _name_order(b) else (b, a)
                conflicts.append(
                    Conflict(
                        channel=channel,
                        cue_a=first.cue,
                        cue_b=second.cue,
                        overlap_start_ms=overlap_start,
                        overlap_end_ms=overlap_end,
                    )
                )

    conflicts.sort(
        key=lambda c: (
            c.channel,
            c.overlap_start_ms,
            c.overlap_end_ms,
            c.cue_a,
            c.cue_b,
        )
    )
    return ScanReport(
        channels_checked=len(by_channel),
        conflicts=conflicts,
        contention_windows=merge_contention_windows(conflicts),
        isolation_plan=plan_isolation(cues),
    )


def merge_contention_windows(conflicts: list[Conflict]) -> list[ContentionWindow]:
    """把同一通道内相交或首尾相接的冲突重叠区间确定性合并为抢值时间窗。

    区间仍按左闭右开处理：按 (起点, 终点) 排序后线性扫描，
    下一区间起点 <= 当前窗口终点（含端点相接）即并入，否则结算当前窗口。
    结果按通道 → 起点 → 终点排序（合并后同通道起点唯一，排序完全确定）。
    """
    by_channel: dict[int, list[Conflict]] = {}
    for conflict in conflicts:
        by_channel.setdefault(conflict.channel, []).append(conflict)

    windows: list[ContentionWindow] = []
    for channel, items in by_channel.items():
        items.sort(key=lambda c: (c.overlap_start_ms, c.overlap_end_ms))
        start: int | None = None
        end = 0
        count = 0
        for item in items:
            if start is not None and item.overlap_start_ms > end:
                windows.append(ContentionWindow(channel, start, end, count))
                start = None
            if start is None:
                start, end, count = item.overlap_start_ms, item.overlap_end_ms, 1
            else:
                end = max(end, item.overlap_end_ms)
                count += 1
        if start is not None:
            windows.append(ContentionWindow(channel, start, end, count))

    windows.sort(key=lambda w: (w.channel, w.start_ms, w.end_ms))
    return windows


def plan_isolation(cues: list[Cue]) -> list[IsolationItem]:
    """求隔离数量最少的临时隔离方案，使余下 cue 在各自通道内互不重叠。

    以每个通道的原始 cue 为候选全局求解（等价于加权区间调度）：
    - 隔离数最少 ⟺ 保留数最多；
    - 隔离总时长更短 ⟺ 保留总时长更长（候选总时长恒定）；
    - 仍并列时，被隔离下标的升序序列字典序更小者优，即优先隔离源数组下标小的 cue。

    逐冲突任选一端隔离的贪心在链式重叠（A∩B、B∩C 而 A∩C 为空）上会多隔离一条，
    因此这里按通道做动态规划取全局最优，再按通道 → 源下标排序输出。
    """
    by_channel: dict[int, list[tuple[int, Cue]]] = {}
    for index, cue in enumerate(cues):
        by_channel.setdefault(cue.channel, []).append((index, cue))

    plan: list[IsolationItem] = []
    for channel, items in by_channel.items():
        for index in _channel_isolation_indices(items):
            cue = cues[index]
            plan.append(
                IsolationItem(
                    index=index,
                    cue=cue.cue,
                    channel=channel,
                    start_ms=cue.start_ms,
                    end_ms=cue.end_ms,
                )
            )
    plan.sort(key=lambda item: (item.channel, item.index))
    return plan


def _channel_isolation_indices(items: list[tuple[int, Cue]]) -> list[int]:
    """单通道内的最优隔离下标（升序）。items 为 (源数组下标, cue) 对。"""
    m = len(items)
    if m < 2:
        return []

    # 第三优先级用位权编码：源下标越小位权越大，等数量前提下
    # "被隔离下标升序序列字典序更小" 等价于被隔离集合的位权总和更大。
    bit_of = {
        index: 1 << (m - 1 - pos)
        for pos, (index, _) in enumerate(sorted(items, key=lambda pair: pair[0]))
    }

    # 按终点升序做加权区间调度；终点相同再按起点、源下标，保证扫描顺序确定。
    seq = sorted(items, key=lambda pair: (pair[1].end_ms, pair[1].start_ms, pair[0]))
    ends = [cue.end_ms for _, cue in seq]

    # dp 状态：只考虑 seq 前 i 个时的最优 (保留数, 保留总时长, 被隔离位权和)。
    count = [0] * (m + 1)
    kept_ms = [0] * (m + 1)
    dropped_bits = [0] * (m + 1)
    for i in range(1, m + 1):
        index, cue = seq[i - 1]
        duration = cue.end_ms - cue.start_ms
        # 半开区间：终点 <= 当前起点即兼容（端点相接可共存）。
        compatible = bisect_right(ends, cue.start_ms, 0, i - 1)
        # 方案一：隔离当前 cue。
        skip = (count[i - 1], kept_ms[i - 1], dropped_bits[i - 1] | bit_of[index])
        # 方案二：保留当前 cue，排在其后且与之相叠的中间项全部隔离。
        keep_bits = dropped_bits[compatible]
        for k in range(compatible, i - 1):
            keep_bits |= bit_of[seq[k][0]]
        keep = (count[compatible] + 1, kept_ms[compatible] + duration, keep_bits)
        count[i], kept_ms[i], dropped_bits[i] = max(skip, keep)

    final_bits = dropped_bits[m]
    return sorted(index for index, bit in bit_of.items() if final_bits & bit)
