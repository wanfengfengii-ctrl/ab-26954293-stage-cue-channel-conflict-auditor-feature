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
    """建议临时隔离的单条原始 cue；source_index 为其在源数组中的下标。"""

    source_index: int
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
    # 连同源数组下标一起分组：隔离方案必须回填每个 cue 的原始下标，
    # 且同名称同区间的重复项要靠源下标稳定决胜。
    indexed = list(enumerate(cues))
    by_channel: dict[int, list[tuple[int, Cue]]] = {}
    for source_index, cue in indexed:
        by_channel.setdefault(cue.channel, []).append((source_index, cue))

    conflicts: list[Conflict] = []
    for channel, items in by_channel.items():
        # 必须按 start_ms 升序扫描：b.start_ms >= a.end_ms 时其后的 cue
        # 起点只会更晚，不可能再与 a 重叠，才能安全提前终止。
        # （若按名称排序，名称居中但时间很靠后的 cue 会触发提前终止，
        # 把名称靠后但实际重叠的 cue 跳过，导致漏判。）
        items.sort(key=lambda pair: _time_order(pair[1]))
        for i, (_, a) in enumerate(items):
            for _, b in items[i + 1 :]:
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
        isolation_plan=plan_isolation(by_channel),
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


def plan_isolation(
    by_channel: dict[int, list[tuple[int, Cue]]],
) -> list[IsolationItem]:
    """求每通道最少临时隔离方案：移除最少 cue 使保留区间互不重叠。

    这是「最多互不重叠区间」问题的全局最优解（加权区间调度 DP），
    不能用「遇到冲突任选一端移除」的贪心代替——链式重叠
    （A∩B、B∩C，但 A 与 C 不相交）下贪心会隔离两个端点，
    而全局只需隔离中间一个。

    目标依次比较：
    1. 隔离数量最少（等价于保留数量最多）；
    2. 隔离总时长（end_ms - start_ms 之和）更短；
    3. 隔离项源数组下标升序序列的字典序更小。

    半开区间端点相接（前一个 end_ms 等于后一个 start_ms）可以共存，
    故前驱按 end_ms <= start_ms 选取。名称与区间完全相同的重复项
    依靠源下标稳定决胜，结果确定且可复现。
    """
    plan: list[IsolationItem] = []
    for channel, pairs in by_channel.items():
        entries = [(idx, cue.start_ms, cue.end_ms) for idx, cue in pairs]
        entries.sort(key=lambda e: (e[2], e[1], e[0]))
        n = len(entries)
        starts = [e[1] for e in entries]
        ends = [e[2] for e in entries]

        # p[i]：满足 end_ms <= start_i 的最后一个下标（含端点相接），无则 -1
        prev: list[int] = [-1] * n
        for i in range(n):
            prev[i] = bisect_right(ends, starts[i], hi=i) - 1

        # states[i]：只考虑前 i+1 个区间时，保留集合的最优
        # (保留数量, 保留总时长, 保留下标集合的有序元组)
        states: list[tuple[int, int, tuple[int, ...]]] = [None] * n  # type: ignore[list-item]
        for i in range(n):
            source_index, start, end = entries[i]
            take_count = 1
            take_duration = end - start
            take_indices = (source_index,)
            if prev[i] >= 0:
                base_count, base_duration, base_indices = states[prev[i]]
                take_count += base_count
                take_duration += base_duration
                take_indices = tuple(_merge_sorted(base_indices, (source_index,)))
            take_state = (take_count, take_duration, take_indices)

            skip_state = states[i - 1] if i > 0 else (0, 0, ())
            # 保留数量最多；并列时保留总时长更长（即隔离总时长更短）；
            # 再并列时保留下标升序序列字典序更大（等价于隔离序列字典序更小）。
            states[i] = take_state if _take_is_better(take_state, skip_state) else skip_state

        kept = set(states[n - 1][2])
        for source_index, cue in pairs:
            if source_index not in kept:
                plan.append(
                    IsolationItem(
                        source_index=source_index,
                        cue=cue.cue,
                        channel=channel,
                        start_ms=cue.start_ms,
                        end_ms=cue.end_ms,
                    )
                )

    plan.sort(key=lambda item: (item.channel, item.source_index))
    return plan


def _merge_sorted(a: tuple[int, ...], b: tuple[int, ...]) -> list[int]:
    """合并两个已按下标升序排列的元组。

    entries 按时间排序，源下标位置任意，DP 前驱链中的下标不一定
    小于当前下标，因此必须真正归并而不能直接拼接。
    """
    merged: list[int] = []
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            merged.append(a[i])
            i += 1
        else:
            merged.append(b[j])
            j += 1
    merged.extend(a[i:])
    merged.extend(b[j:])
    return merged


def _take_is_better(
    take: tuple[int, int, tuple[int, ...]],
    skip: tuple[int, int, tuple[int, ...]],
) -> bool:
    """保留方案比较：数量 → 总时长 → 下标序列字典序（越大越优）。"""
    if take[0] != skip[0]:
        return take[0] > skip[0]
    if take[1] != skip[1]:
        return take[1] > skip[1]
    return take[2] > skip[2]
