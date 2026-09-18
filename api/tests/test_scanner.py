"""核心扫描规则测试：区间语义、重叠段计算、排序。"""

import itertools
import random

from app.scanner import (
    Conflict,
    Cue,
    merge_contention_windows,
    plan_isolation,
    scan_conflicts,
)


def cue(name: str, channel: int, start: int, end: int) -> Cue:
    return Cue(cue=name, channel=channel, start_ms=start, end_ms=end)


def conflict(channel: int, start: int, end: int) -> Conflict:
    return Conflict(
        channel=channel,
        cue_a="A",
        cue_b="B",
        overlap_start_ms=start,
        overlap_end_ms=end,
    )


def brute_force(cues: list[Cue]) -> list[tuple]:
    """独立的朴素两两比较实现，用于交叉验证扫描器结果。"""
    found = []
    for a, b in itertools.combinations(cues, 2):
        if a.channel != b.channel:
            continue
        lo = max(a.start_ms, b.start_ms)
        hi = min(a.end_ms, b.end_ms)
        if lo >= hi:
            continue
        first, second = (
            (a, b)
            if (a.cue, a.start_ms, a.end_ms) <= (b.cue, b.start_ms, b.end_ms)
            else (b, a)
        )
        found.append((a.channel, lo, hi, first.cue, second.cue))
    found.sort()
    return found


class TestOverlapSemantics:
    def test_touching_endpoints_are_not_conflicts(self):
        # [0,100) 与 [100,200) 仅端点相接，不冲突
        report = scan_conflicts([cue("A", 1, 0, 100), cue("B", 1, 100, 200)])
        assert report.conflicts == []
        assert report.channels_checked == 1

    def test_half_open_overlap_segment(self):
        report = scan_conflicts([cue("A", 1, 0, 150), cue("B", 1, 100, 300)])
        assert len(report.conflicts) == 1
        c = report.conflicts[0]
        assert (c.overlap_start_ms, c.overlap_end_ms) == (100, 150)

    def test_contained_interval_overlap_is_inner_interval(self):
        report = scan_conflicts([cue("A", 1, 0, 1000), cue("B", 1, 200, 300)])
        assert len(report.conflicts) == 1
        c = report.conflicts[0]
        assert (c.overlap_start_ms, c.overlap_end_ms) == (200, 300)

    def test_single_millisecond_overlap_counts(self):
        report = scan_conflicts([cue("A", 1, 0, 101), cue("B", 1, 100, 200)])
        assert len(report.conflicts) == 1
        c = report.conflicts[0]
        assert (c.overlap_start_ms, c.overlap_end_ms) == (100, 101)

    def test_disjoint_intervals_no_conflict(self):
        report = scan_conflicts([cue("A", 1, 0, 50), cue("B", 1, 60, 90)])
        assert report.conflicts == []

    def test_channels_are_scanned_independently(self):
        report = scan_conflicts(
            [cue("A", 1, 0, 100), cue("B", 2, 50, 150)]
        )
        assert report.conflicts == []
        assert report.channels_checked == 2

    def test_three_way_overlap_yields_all_pairs(self):
        report = scan_conflicts(
            [cue("A", 1, 0, 100), cue("B", 1, 50, 150), cue("C", 1, 75, 200)]
        )
        pairs = {(c.cue_a, c.cue_b) for c in report.conflicts}
        assert pairs == {("A", "B"), ("A", "C"), ("B", "C")}

    def test_empty_input(self):
        report = scan_conflicts([])
        assert report.channels_checked == 0
        assert report.conflicts == []


class TestResultOrdering:
    def test_pair_members_normalized_lexicographically(self):
        # 先出现名字靠后的 cue，输出仍按字典序排列
        report = scan_conflicts([cue("Zeta", 1, 0, 100), cue("Alpha", 1, 50, 150)])
        assert report.conflicts[0].cue_a == "Alpha"
        assert report.conflicts[0].cue_b == "Zeta"

    def test_sorted_by_channel_then_overlap_then_names(self):
        cues = [
            cue("B", 2, 10, 90),   # 通道 2: [10,90)
            cue("A", 2, 0, 50),    # 通道 2: 与 B 重叠 [10,50)
            cue("Y", 1, 100, 200), # 通道 1
            cue("X", 1, 150, 250), # 通道 1: 与 Y 重叠 [150,200)
            cue("M", 1, 120, 130), # 通道 1: 与 Y 重叠 [120,130)，与 X 不重叠
        ]
        report = scan_conflicts(cues)
        keys = [
            (c.channel, c.overlap_start_ms, c.overlap_end_ms, c.cue_a, c.cue_b)
            for c in report.conflicts
        ]
        assert keys == [
            (1, 120, 130, "M", "Y"),
            (1, 150, 200, "X", "Y"),
            (2, 10, 50, "A", "B"),
        ]

    def test_same_channel_sorted_by_overlap_start_then_end_then_names(self):
        cues = [
            cue("B", 1, 0, 100),
            cue("A", 1, 50, 60),   # 与 B、D 均重叠 [50,60)
            cue("D", 1, 50, 80),   # 与 A 重叠 [50,60)，与 B 重叠 [50,80)
            cue("C", 1, 70, 90),   # 与 B 重叠 [70,90)，与 D 重叠 [70,80)
        ]
        report = scan_conflicts(cues)
        keys = [
            (c.overlap_start_ms, c.overlap_end_ms, c.cue_a, c.cue_b)
            for c in report.conflicts
        ]
        assert keys == [
            (50, 60, "A", "B"),
            (50, 60, "A", "D"),
            (50, 80, "B", "D"),
            (70, 80, "C", "D"),
            (70, 90, "B", "C"),
        ]

    def test_same_cue_name_can_conflict_with_itself(self):
        report = scan_conflicts([cue("A", 1, 0, 100), cue("A", 1, 50, 150)])
        assert len(report.conflicts) == 1
        c = report.conflicts[0]
        assert (c.cue_a, c.cue_b) == ("A", "A")
        assert (c.overlap_start_ms, c.overlap_end_ms) == (50, 100)


class TestChannelsChecked:
    def test_counts_distinct_channels(self):
        report = scan_conflicts(
            [cue("A", 1, 0, 10), cue("B", 1, 20, 30), cue("C", 512, 0, 10)]
        )
        assert report.channels_checked == 2


class TestNameOrderVsTimeOrder:
    """回归：名称顺序与时间顺序不一致时不得漏判（曾因此误报可放行）。"""

    def test_middle_name_far_future_cue_must_not_hide_overlap(self):
        report = scan_conflicts(
            [
                cue("A", 1, 0, 1000),    # 长渐变
                cue("B", 1, 5000, 6000), # 名称居中，但时间远在将来
                cue("C", 1, 500, 600),   # 名称靠后，但与 A 实际重叠
            ]
        )
        assert [
            (c.cue_a, c.cue_b, c.overlap_start_ms, c.overlap_end_ms)
            for c in report.conflicts
        ] == [("A", "C", 500, 600)]

    def test_reverse_name_and_time_order(self):
        report = scan_conflicts(
            [
                cue("C", 1, 0, 100),
                cue("B", 1, 50, 150),
                cue("A", 1, 75, 200),
            ]
        )
        assert {
            (c.cue_a, c.cue_b, c.overlap_start_ms, c.overlap_end_ms)
            for c in report.conflicts
        } == {
            ("B", "C", 50, 100),
            ("A", "C", 75, 100),
            ("A", "B", 75, 150),
        }

    def test_input_order_does_not_matter(self):
        base = [
            cue("B", 1, 5000, 6000),
            cue("A", 1, 0, 1000),
            cue("C", 1, 500, 600),
        ]
        shuffled = [base[2], base[0], base[1]]
        assert scan_conflicts(base).conflicts == scan_conflicts(shuffled).conflicts


class TestBruteForceCrossCheck:
    def test_matches_brute_force_under_scrambled_name_time_orders(self):
        rng = random.Random(20260914)
        for _ in range(300):
            cues = []
            for _ in range(rng.randint(0, 8)):
                start = rng.randint(0, 50)
                cues.append(
                    Cue(
                        cue=chr(ord("A") + rng.randint(0, 4)),
                        channel=rng.randint(1, 3),
                        start_ms=start,
                        end_ms=start + rng.randint(1, 20),
                    )
                )
            report = scan_conflicts(cues)
            got = [
                (c.channel, c.overlap_start_ms, c.overlap_end_ms, c.cue_a, c.cue_b)
                for c in report.conflicts
            ]
            assert got == brute_force(cues)


class TestContentionWindows:
    def window_keys(self, report) -> list[tuple]:
        return [
            (w.channel, w.start_ms, w.end_ms, w.conflict_count)
            for w in report.contention_windows
        ]

    def test_empty_when_no_conflicts(self):
        assert merge_contention_windows([]) == []
        report = scan_conflicts([cue("A", 1, 0, 100), cue("B", 1, 100, 200)])
        assert report.contention_windows == []

    def test_single_conflict_forms_single_window(self):
        windows = merge_contention_windows([conflict(1, 500, 1000)])
        assert [(w.channel, w.start_ms, w.end_ms, w.conflict_count) for w in windows] == [
            (1, 500, 1000, 1)
        ]

    def test_chain_merge_across_multiple_conflicts(self):
        # [0,10) 与 [14,20) 本不相交，经 [5,15) 链式传递合并为一个窗口
        windows = merge_contention_windows(
            [conflict(1, 0, 10), conflict(1, 5, 15), conflict(1, 14, 20)]
        )
        assert [(w.start_ms, w.end_ms, w.conflict_count) for w in windows] == [
            (0, 20, 3)
        ]

    def test_touching_endpoints_merge(self):
        # 重叠区间端点相接（一个的终点等于另一个的起点）也合并
        windows = merge_contention_windows(
            [conflict(1, 0, 100), conflict(1, 100, 200)]
        )
        assert [(w.start_ms, w.end_ms, w.conflict_count) for w in windows] == [
            (0, 200, 2)
        ]

    def test_gap_does_not_merge(self):
        windows = merge_contention_windows(
            [conflict(1, 0, 10), conflict(1, 11, 20)]
        )
        assert [(w.start_ms, w.end_ms, w.conflict_count) for w in windows] == [
            (0, 10, 1),
            (11, 20, 1),
        ]

    def test_contained_interval_extends_nothing_but_counts(self):
        windows = merge_contention_windows(
            [conflict(1, 0, 100), conflict(1, 20, 30)]
        )
        assert [(w.start_ms, w.end_ms, w.conflict_count) for w in windows] == [
            (0, 100, 2)
        ]

    def test_channels_are_merged_independently(self):
        # 不同通道上完全相同的区间不得互相合并
        windows = merge_contention_windows(
            [conflict(1, 0, 100), conflict(2, 0, 100), conflict(2, 50, 150)]
        )
        assert [(w.channel, w.start_ms, w.end_ms, w.conflict_count) for w in windows] == [
            (1, 0, 100, 1),
            (2, 0, 150, 2),
        ]

    def test_windows_sorted_by_channel_then_start(self):
        windows = merge_contention_windows(
            [
                conflict(2, 0, 10),
                conflict(1, 500, 600),
                conflict(1, 0, 100),
            ]
        )
        assert [(w.channel, w.start_ms) for w in windows] == [(1, 0), (1, 500), (2, 0)]

    def test_scan_report_integrates_windows_from_real_conflicts(self):
        # 三方两两重叠：3 条冲突的重叠区间 [50,100)/[75,100)/[75,150) 合并为一个窗口
        report = scan_conflicts(
            [cue("A", 1, 0, 100), cue("B", 1, 50, 150), cue("C", 1, 75, 200)]
        )
        assert len(report.conflicts) == 3
        assert self.window_keys(report) == [(1, 50, 150, 3)]

    def test_scan_report_chain_and_touching_merge(self):
        # A-B 重叠 [100,150)，A-C 重叠 [150,180)：端点相接合并为 [100,180)
        report = scan_conflicts(
            [
                cue("A", 1, 0, 200),
                cue("B", 1, 100, 150),
                cue("C", 1, 150, 180),
            ]
        )
        assert len(report.conflicts) == 2
        assert self.window_keys(report) == [(1, 100, 180, 2)]

    def test_scan_report_keeps_channels_separate(self):
        report = scan_conflicts(
            [
                cue("A", 1, 0, 100),
                cue("B", 1, 50, 150),
                cue("C", 2, 0, 100),
                cue("D", 2, 50, 150),
            ]
        )
        assert self.window_keys(report) == [(1, 50, 100, 1), (2, 50, 100, 1)]


def brute_force_isolation(cues: list[Cue]) -> list[int]:
    """独立暴力枚举：数量最少 → 隔离总时长更短 → 下标升序序列字典序更小。"""
    best: tuple | None = None
    for mask in range(1 << len(cues)):
        removed = [i for i in range(len(cues)) if mask >> i & 1]
        kept = [i for i in range(len(cues)) if not mask >> i & 1]
        if any(
            cues[a].channel == cues[b].channel
            and max(cues[a].start_ms, cues[b].start_ms)
            < min(cues[a].end_ms, cues[b].end_ms)
            for a, b in itertools.combinations(kept, 2)
        ):
            continue
        key = (
            len(removed),
            sum(cues[i].end_ms - cues[i].start_ms for i in removed),
            removed,
        )
        if best is None or key < best:
            best = key
    return best[2]


class TestIsolationPlan:
    def plan_keys(self, cues: list[Cue]) -> list[tuple]:
        return [
            (item.channel, item.index, item.cue, item.start_ms, item.end_ms)
            for item in plan_isolation(cues)
        ]

    def test_empty_when_no_conflicts(self):
        assert plan_isolation([cue("A", 1, 0, 100), cue("B", 1, 100, 200)]) == []
        assert plan_isolation([]) == []

    def test_touching_endpoints_coexist_without_isolation(self):
        # 端点相接不算重叠，两条都可保留，无需隔离
        cues = [cue("A", 1, 0, 100), cue("B", 1, 100, 200), cue("C", 1, 200, 250)]
        assert plan_isolation(cues) == []

    def test_chain_isolates_single_middle_cue(self):
        # 链式重叠 A∩B、B∩C（A∩C 为空）：逐冲突任选端点的贪心会隔离两条，
        # 全局最优只隔离中间的 B
        cues = [cue("A", 1, 0, 10), cue("B", 1, 5, 15), cue("C", 1, 10, 20)]
        assert self.plan_keys(cues) == [(1, 1, "B", 5, 15)]

    def test_long_chain_keeps_alternating_cues(self):
        # 5 条依次相叠的链：隔离第 2、4 条即可全部走台
        cues = [cue(f"C{i}", 1, i * 10, i * 10 + 15) for i in range(5)]
        assert [item.index for item in plan_isolation(cues)] == [1, 3]

    def test_shorter_total_isolation_duration_wins(self):
        # 两条相叠：各隔离一条数量相同，隔离时长更短的 B（10ms）而非 A（100ms）
        cues = [cue("A", 1, 0, 100), cue("B", 1, 50, 60)]
        assert self.plan_keys(cues) == [(1, 1, "B", 50, 60)]

    def test_identical_duplicates_decided_by_source_index(self):
        # 名称与区间完全相同的重复项：数量、时长都并列，隔离源下标更小者
        cues = [cue("X", 1, 0, 100), cue("X", 1, 0, 100)]
        assert self.plan_keys(cues) == [(1, 0, "X", 0, 100)]

    def test_index_sequence_breaks_remaining_ties(self):
        # 数量与隔离总时长均并列时，被隔离下标升序序列字典序更小者优
        cues = [
            cue("A", 1, 0, 10),   # 下标 0
            cue("B", 1, 5, 15),   # 下标 1
            cue("C", 1, 10, 20),  # 下标 2
            cue("D", 1, 15, 25),  # 下标 3
        ]
        # 四条链最少隔离两条，可选 {0,2} / {1,2} / {1,3}，时长都是 20ms，
        # 下标升序序列 [0, 2] 字典序最小
        assert [item.index for item in plan_isolation(cues)] == [0, 2]

    def test_plan_sorted_by_channel_then_index(self):
        cues = [
            cue("P", 2, 0, 10),   # 下标 0，通道 2，与 Q 相叠
            cue("Q", 2, 5, 15),   # 下标 1，通道 2
            cue("R", 1, 0, 10),   # 下标 2，通道 1，与 S 相叠
            cue("S", 1, 5, 15),   # 下标 3，通道 1
        ]
        # 通道 1 隔离 R（下标 2），通道 2 隔离 P（下标 0）；输出按通道 → 下标
        assert self.plan_keys(cues) == [
            (1, 2, "R", 0, 10),
            (2, 0, "P", 0, 10),
        ]

    def test_channels_optimized_independently(self):
        # 通道 1 的链式重叠与通道 2 的单点重叠互不影响
        cues = [
            cue("A", 1, 0, 10),
            cue("B", 1, 5, 15),
            cue("C", 1, 10, 20),
            cue("X", 2, 0, 100),
            cue("Y", 2, 50, 60),
        ]
        assert self.plan_keys(cues) == [(1, 1, "B", 5, 15), (2, 4, "Y", 50, 60)]

    def test_scan_report_integrates_isolation_plan(self):
        report = scan_conflicts(
            [cue("A", 1, 0, 10), cue("B", 1, 5, 15), cue("C", 1, 10, 20)]
        )
        assert len(report.conflicts) == 2
        assert [(i.index, i.cue) for i in report.isolation_plan] == [(1, "B")]

    def test_remaining_cues_never_overlap(self):
        # 性质：按方案隔离后，余下 cue 在各自通道内互不重叠
        rng = random.Random(20260918)
        for _ in range(200):
            cues = []
            for _ in range(rng.randint(0, 10)):
                start = rng.randint(0, 40)
                cues.append(
                    cue(
                        chr(ord("A") + rng.randint(0, 3)),
                        rng.randint(1, 3),
                        start,
                        start + rng.randint(1, 15),
                    )
                )
            removed = {item.index for item in plan_isolation(cues)}
            kept = [c for i, c in enumerate(cues) if i not in removed]
            assert scan_conflicts(kept).conflicts == []

    def test_matches_brute_force_under_scrambled_inputs(self):
        rng = random.Random(20260918)
        for _ in range(300):
            cues = []
            for _ in range(rng.randint(0, 9)):
                start = rng.randint(0, 30)
                cues.append(
                    cue(
                        chr(ord("A") + rng.randint(0, 3)),
                        rng.randint(1, 3),
                        start,
                        start + rng.randint(1, 12),
                    )
                )
            got = sorted(item.index for item in plan_isolation(cues))
            assert got == brute_force_isolation(cues)
