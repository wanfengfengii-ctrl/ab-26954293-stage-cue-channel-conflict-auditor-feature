"""核心扫描规则测试：区间语义、重叠段计算、排序。"""

import itertools
import random

from app.scanner import (
    Conflict,
    Cue,
    IsolationItem,
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


def _isolation_key(item: IsolationItem) -> tuple[int, int]:
    return (item.channel, item.source_index)


def _brute_force_isolation(cues: list[Cue]) -> list[int]:
    """独立暴力实现：枚举全部保留子集，按三级规则选最优隔离下标序列。"""
    n = len(cues)

    def compatible(kept: list[int]) -> bool:
        for a, b in itertools.combinations(kept, 2):
            x, y = cues[a], cues[b]
            if (
                x.channel == y.channel
                and max(x.start_ms, y.start_ms) < min(x.end_ms, y.end_ms)
            ):
                return False
        return True

    best: tuple[int, int, tuple[int, ...]] | None = None
    for mask in range(1 << n):
        kept = [i for i in range(n) if mask & (1 << i)]
        if not compatible(kept):
            continue
        removed = tuple(i for i in range(n) if not (mask & (1 << i)))
        total = sum(cues[i].end_ms - cues[i].start_ms for i in removed)
        candidate = (len(removed), total, removed)
        if best is None or candidate < best:
            best = candidate
    return list(best[2])


class TestIsolationPlan:
    def test_no_conflict_empty_plan(self):
        # 端点相接可共存，无需隔离
        report = scan_conflicts([cue("A", 1, 0, 100), cue("B", 1, 100, 200)])
        assert report.isolation_plan == []

    def test_empty_input(self):
        assert plan_isolation({}) == []
        assert scan_conflicts([]).isolation_plan == []

    def test_pair_overlap_isolates_shorter_by_duration_tiebreak(self):
        # 两条重叠：隔离 1 条；时长决胜，隔离更短的那条
        report = scan_conflicts(
            [cue("长", 1, 0, 100), cue("短", 1, 50, 60)]
        )
        assert [_isolation_key(i) for i in report.isolation_plan] == [(1, 1)]
        plan = report.isolation_plan[0]
        assert (plan.cue, plan.start_ms, plan.end_ms) == ("短", 50, 60)

    def test_pair_overlap_same_duration_isolated_by_source_index(self):
        # 时长相同：隔离源下标升序序列字典序更小者 → 隔离前面的（保留后面的）
        report = scan_conflicts(
            [cue("甲", 1, 0, 100), cue("Z", 1, 0, 100)]
        )
        assert [i.source_index for i in report.isolation_plan] == [0]

    def test_chain_greedy_trap_isolates_middle(self):
        # 链式：A[0,10)∩B[5,15)，B∩C[10,20)（A 与 C 端点相接可共存）
        # 逐冲突任选一端的贪心会隔 A、C 两个，全局最优只隔离中间 B
        report = scan_conflicts(
            [
                cue("A", 1, 0, 10),
                cue("B", 1, 5, 15),
                cue("C", 1, 10, 20),
            ]
        )
        assert [i.source_index for i in report.isolation_plan] == [1]
        assert report.isolation_plan[0].cue == "B"

    def test_long_chain_global_optimum_beats_endpoint_greedy(self):
        # 纯链 A-B-C-D（相邻重叠、隔一个不冲突）：
        # 全局最优保留 {B,D}（下标 1、3），隔离 0、2 共 2 条；
        # 而「逐冲突二选一移除端点再重扫」的贪心在三段链上会移除 3 条。
        cues = [
            cue("A", 1, 0, 10),
            cue("B", 1, 5, 15),
            cue("C", 1, 12, 22),
            cue("D", 1, 20, 30),
        ]
        assert [i.source_index for i in scan_conflicts(cues).isolation_plan] == [0, 2]

    def test_endpoint_greedy_over_isolates_on_chain(self):
        # 显式复现验收反例：固定移除每个冲突对中较早一端、循环重扫的贪心，
        # 在三段链上隔离 2 条；全局解只隔离中间 1 条。
        cues = [
            cue("A", 1, 0, 10),
            cue("B", 1, 5, 15),
            cue("C", 1, 10, 20),
        ]

        def greedy_removed() -> set[int]:
            removed: set[int] = set()
            changed = True
            while changed:
                changed = False
                for a, b in itertools.combinations(range(len(cues)), 2):
                    if a in removed or b in removed:
                        continue
                    x, y = cues[a], cues[b]
                    if max(x.start_ms, y.start_ms) < min(x.end_ms, y.end_ms):
                        removed.add(a)  # 固定移除冲突对较早的一端
                        changed = True
                        break
            return removed

        assert greedy_removed() == {0, 1}
        assert {i.source_index for i in scan_conflicts(cues).isolation_plan} == {1}

    def test_touching_intervals_can_coexist_so_nothing_isolated(self):
        # 全部首尾相接：[0,10)[10,20)[20,30)，互不冲突，无需隔离
        report = scan_conflicts(
            [
                cue("A", 1, 0, 10),
                cue("B", 1, 10, 20),
                cue("C", 1, 20, 30),
            ]
        )
        assert report.isolation_plan == []

    def test_identical_duplicates_stable_by_source_index(self):
        # 名称与区间完全相同的重复项：必须隔一个，按源下标稳定决胜（隔 0 留 1）
        report = scan_conflicts(
            [
                cue("X", 1, 0, 100),
                cue("X", 1, 0, 100),
            ]
        )
        assert [i.source_index for i in report.isolation_plan] == [0]

    def test_identical_duplicates_keep_one_out_of_three(self):
        # 三条完全相同：保留 1 条即可，隔离前两个（下标 0、1）
        report = scan_conflicts(
            [
                cue("X", 1, 0, 100),
                cue("X", 1, 0, 100),
                cue("X", 1, 0, 100),
            ]
        )
        assert [i.source_index for i in report.isolation_plan] == [0, 1]

    def test_duration_tiebreak_prefers_isolating_shorter_cues(self):
        # 通道上两段互不相连的冲突对，每对都要隔离 1 条（总数恒为 2），
        # 此时由隔离总时长决胜：每对隔离更短的那条（10+10=20），
        # 而不是两条长 cue（100+100=200）
        report = scan_conflicts(
            [
                cue("长甲", 1, 0, 100),
                cue("短甲", 1, 0, 10),
                cue("短乙", 1, 200, 210),
                cue("长乙", 1, 200, 300),
            ]
        )
        assert [i.source_index for i in report.isolation_plan] == [1, 2]
        assert sum(i.end_ms - i.start_ms for i in report.isolation_plan) == 20

    def test_channels_solved_independently(self):
        report = scan_conflicts(
            [
                cue("A", 1, 0, 10),
                cue("B", 1, 5, 15),
                cue("C", 2, 0, 10),
                cue("D", 2, 6, 16),
            ]
        )
        assert [_isolation_key(i) for i in report.isolation_plan] == [(1, 0), (2, 2)]

    def test_plan_items_carry_source_data(self):
        report = scan_conflicts(
            [
                cue("开场", 7, 0, 100),
                cue("追光", 7, 50, 150),
            ]
        )
        assert report.isolation_plan == [
            IsolationItem(
                source_index=0,
                cue="开场",
                channel=7,
                start_ms=0,
                end_ms=100,
            )
        ]

    def test_plan_sorted_by_channel_then_source_index(self):
        # 源数组中通道 2 的 cue 在前：输出仍必须按通道再按下标
        cues = [
            cue("A", 2, 0, 10),   # idx0 ch2
            cue("B", 2, 5, 15),   # idx1 ch2
            cue("C", 1, 0, 10),   # idx2 ch1
            cue("D", 1, 5, 15),   # idx3 ch1
        ]
        report = scan_conflicts(cues)
        keys = [(i.channel, i.source_index) for i in report.isolation_plan]
        assert keys == [(1, 2), (2, 0)]

    def test_kept_intervals_are_conflict_free(self):
        # 任意方案落地后，保留下来的 cue 不应再产生任何冲突
        rng = random.Random(20260918)
        for _ in range(200):
            cues = [
                cue(
                    chr(ord("A") + rng.randint(0, 4)),
                    rng.randint(1, 3),
                    (s := rng.randint(0, 50)),
                    s + rng.randint(1, 20),
                )
                for _ in range(rng.randint(0, 10))
            ]
            report = scan_conflicts(cues)
            removed = {i.source_index for i in report.isolation_plan}
            kept = [cues[i] for i in range(len(cues)) if i not in removed]
            assert scan_conflicts(kept).conflicts == []

    def test_matches_brute_force_under_random_inputs(self):
        rng = random.Random(99)
        for _ in range(400):
            cues = []
            for _ in range(rng.randint(0, 8)):
                start = rng.randint(0, 30)
                cues.append(
                    Cue(
                        cue=chr(ord("A") + rng.randint(0, 3)),
                        channel=rng.randint(1, 3),
                        start_ms=start,
                        end_ms=start + rng.randint(1, 15),
                    )
                )
            got = sorted(i.source_index for i in scan_conflicts(cues).isolation_plan)
            assert got == _brute_force_isolation(cues)
