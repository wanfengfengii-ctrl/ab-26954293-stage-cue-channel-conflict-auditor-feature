"""端到端验收：对真实运行的 web/api 服务发起真实 HTTP 请求。

默认经 WEB_URL（nginx 同源代理，即浏览器实际路径）调用分析接口，
覆盖文件校验、冲突扫描与结果排序的完整规则。
"""

import json

import requests


def analyze(base_url: str, payload) -> requests.Response:
    if not isinstance(payload, (str, bytes)):
        payload = json.dumps(payload, ensure_ascii=False)
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return requests.post(
        f"{base_url}/api/analyze",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=10,
    )


class TestStackWiring:
    def test_web_serves_frontend(self, web_url):
        resp = requests.get(web_url, timeout=10)
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("Content-Type", "")

    def test_api_health(self, api_url):
        resp = requests.get(f"{api_url}/healthz", timeout=10)
        assert resp.status_code == 200
        assert resp.json() == {"status": "healthy"}

    def test_web_proxies_analyze_to_api(self, web_url):
        resp = analyze(web_url, [])
        assert resp.status_code == 200
        assert resp.json()["channels_checked"] == 0


class TestConflictScanning:
    def test_overlap_reported_with_exact_interval(self, web_url):
        payload = [
            {"cue": "开场", "channel": 1, "start_ms": 0, "end_ms": 1000},
            {"cue": "追光", "channel": 1, "start_ms": 500, "end_ms": 1500},
        ]
        resp = analyze(web_url, payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["channels_checked"] == 1
        assert body["conflicts"] == [
            {
                "channel": 1,
                "cue_a": "开场",
                "cue_b": "追光",
                "overlap_start_ms": 500,
                "overlap_end_ms": 1000,
            }
        ]

    def test_touching_endpoints_do_not_conflict(self, web_url):
        payload = [
            {"cue": "A", "channel": 1, "start_ms": 0, "end_ms": 100},
            {"cue": "B", "channel": 1, "start_ms": 100, "end_ms": 200},
        ]
        body = analyze(web_url, payload).json()
        assert body["conflicts"] == []
        assert body["channels_checked"] == 1

    def test_contained_interval_reports_inner_range(self, web_url):
        payload = [
            {"cue": "长渐变", "channel": 7, "start_ms": 0, "end_ms": 5000},
            {"cue": "短渐变", "channel": 7, "start_ms": 1200, "end_ms": 1800},
        ]
        body = analyze(web_url, payload).json()
        conflict = body["conflicts"][0]
        assert (conflict["overlap_start_ms"], conflict["overlap_end_ms"]) == (1200, 1800)

    def test_results_sorted_by_channel_overlap_and_names(self, web_url):
        payload = [
            {"cue": "B", "channel": 2, "start_ms": 10, "end_ms": 90},
            {"cue": "A", "channel": 2, "start_ms": 0, "end_ms": 50},
            {"cue": "Y", "channel": 1, "start_ms": 100, "end_ms": 200},
            {"cue": "X", "channel": 1, "start_ms": 150, "end_ms": 250},
        ]
        body = analyze(web_url, payload).json()
        assert body["conflicts"] == [
            {
                "channel": 1,
                "cue_a": "X",
                "cue_b": "Y",
                "overlap_start_ms": 150,
                "overlap_end_ms": 200,
            },
            {
                "channel": 2,
                "cue_a": "A",
                "cue_b": "B",
                "overlap_start_ms": 10,
                "overlap_end_ms": 50,
            },
        ]

    def test_three_way_overlap_lists_all_pairs(self, web_url):
        payload = [
            {"cue": "A", "channel": 3, "start_ms": 0, "end_ms": 100},
            {"cue": "B", "channel": 3, "start_ms": 50, "end_ms": 150},
            {"cue": "C", "channel": 3, "start_ms": 75, "end_ms": 200},
        ]
        body = analyze(web_url, payload).json()
        pairs = {(c["cue_a"], c["cue_b"]) for c in body["conflicts"]}
        assert pairs == {("A", "B"), ("A", "C"), ("B", "C")}

    def test_channel_boundaries_1_and_512_accepted(self, web_url):
        payload = [
            {"cue": "低", "channel": 1, "start_ms": 0, "end_ms": 10},
            {"cue": "高", "channel": 512, "start_ms": 0, "end_ms": 10},
        ]
        resp = analyze(web_url, payload)
        assert resp.status_code == 200
        assert resp.json()["channels_checked"] == 2

    def test_name_order_never_hides_real_overlap(self, web_url):
        # 回归：B 名称居中但时间远在将来，不得因此漏判 A 与 C 的重叠而误报可放行
        payload = [
            {"cue": "A-长渐变", "channel": 5, "start_ms": 0, "end_ms": 1000},
            {"cue": "B-远景", "channel": 5, "start_ms": 5000, "end_ms": 6000},
            {"cue": "C-叠加", "channel": 5, "start_ms": 400, "end_ms": 700},
        ]
        resp = analyze(web_url, payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["conflict_count"] == 1
        assert body["conflicts"] == [
            {
                "channel": 5,
                "cue_a": "A-长渐变",
                "cue_b": "C-叠加",
                "overlap_start_ms": 400,
                "overlap_end_ms": 700,
            }
        ]


class TestContentionWindows:
    def test_chain_merge_across_multiple_conflicts(self, web_url):
        # 重叠区间 [10,50)/[40,90)/[40,50)/[80,90)/[80,130) 链式合并为一个窗口
        payload = [
            {"cue": "A", "channel": 1, "start_ms": 0, "end_ms": 90},
            {"cue": "B", "channel": 1, "start_ms": 10, "end_ms": 50},
            {"cue": "C", "channel": 1, "start_ms": 40, "end_ms": 130},
            {"cue": "D", "channel": 1, "start_ms": 80, "end_ms": 200},
        ]
        resp = analyze(web_url, payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["conflict_count"] == 5
        assert body["contention_windows"] == [
            {"channel": 1, "start_ms": 10, "end_ms": 130, "conflict_count": 5}
        ]

    def test_touching_windows_merge(self, web_url):
        # 冲突重叠区间 [100,150) 与 [150,180) 端点相接，合并为 [100,180)
        payload = [
            {"cue": "A", "channel": 1, "start_ms": 0, "end_ms": 200},
            {"cue": "B", "channel": 1, "start_ms": 100, "end_ms": 150},
            {"cue": "C", "channel": 1, "start_ms": 150, "end_ms": 180},
        ]
        body = analyze(web_url, payload).json()
        assert body["conflict_count"] == 2
        assert body["contention_windows"] == [
            {"channel": 1, "start_ms": 100, "end_ms": 180, "conflict_count": 2}
        ]

    def test_windows_isolated_per_channel_and_sorted(self, web_url):
        payload = [
            {"cue": "A", "channel": 2, "start_ms": 0, "end_ms": 100},
            {"cue": "B", "channel": 2, "start_ms": 50, "end_ms": 150},
            {"cue": "C", "channel": 1, "start_ms": 0, "end_ms": 100},
            {"cue": "D", "channel": 1, "start_ms": 50, "end_ms": 150},
            {"cue": "E", "channel": 1, "start_ms": 500, "end_ms": 600},
            {"cue": "F", "channel": 1, "start_ms": 550, "end_ms": 700},
        ]
        body = analyze(web_url, payload).json()
        assert body["contention_windows"] == [
            {"channel": 1, "start_ms": 50, "end_ms": 100, "conflict_count": 1},
            {"channel": 1, "start_ms": 550, "end_ms": 600, "conflict_count": 1},
            {"channel": 2, "start_ms": 50, "end_ms": 100, "conflict_count": 1},
        ]

    def test_no_conflicts_means_no_windows(self, web_url):
        payload = [
            {"cue": "A", "channel": 1, "start_ms": 0, "end_ms": 100},
            {"cue": "B", "channel": 1, "start_ms": 100, "end_ms": 200},
        ]
        body = analyze(web_url, payload).json()
        assert body["conflicts"] == []
        assert body["contention_windows"] == []

    def test_422_response_has_no_windows(self, web_url):
        payload = [{"cue": "A", "channel": 0, "start_ms": 0, "end_ms": 10}]
        resp = analyze(web_url, payload)
        assert resp.status_code == 422
        body = resp.json()
        assert "contention_windows" not in body
        assert "conflicts" not in body


class TestIsolationPlan:
    def test_chain_greedy_trap_needs_only_one_isolation(self, web_url):
        # 链式重叠 A∩B、B∩C，A 与 C 端点相接可共存：
        # 逐冲突任选一端的贪心会隔离两个端点，全局解只隔离中间 B
        payload = [
            {"cue": "A", "channel": 1, "start_ms": 0, "end_ms": 10},
            {"cue": "B", "channel": 1, "start_ms": 5, "end_ms": 15},
            {"cue": "C", "channel": 1, "start_ms": 10, "end_ms": 20},
        ]
        body = analyze(web_url, payload).json()
        assert body["conflict_count"] == 2
        assert body["isolation_plan"] == [
            {"source_index": 1, "cue": "B", "channel": 1, "start_ms": 5, "end_ms": 15}
        ]

    def test_longer_chain_beats_endpoint_greedy(self, web_url):
        # 四段纯链（相邻重叠、隔一个不冲突）：全局隔离 2 条，
        # 而固定移除冲突对较早一端的贪心会隔离 3 条
        payload = [
            {"cue": "A", "channel": 3, "start_ms": 0, "end_ms": 10},
            {"cue": "B", "channel": 3, "start_ms": 5, "end_ms": 15},
            {"cue": "C", "channel": 3, "start_ms": 12, "end_ms": 22},
            {"cue": "D", "channel": 3, "start_ms": 20, "end_ms": 30},
        ]
        body = analyze(web_url, payload).json()
        assert [item["source_index"] for item in body["isolation_plan"]] == [0, 2]

    def test_touching_endpoints_coexist_without_isolation(self, web_url):
        payload = [
            {"cue": "A", "channel": 1, "start_ms": 0, "end_ms": 100},
            {"cue": "B", "channel": 1, "start_ms": 100, "end_ms": 200},
            {"cue": "C", "channel": 1, "start_ms": 200, "end_ms": 300},
        ]
        body = analyze(web_url, payload).json()
        assert body["conflict_count"] == 0
        assert body["isolation_plan"] == []

    def test_identical_duplicates_tie_broken_by_source_index(self, web_url):
        # 名称与区间完全相同的重复项：必须隔离其一，按源下标稳定决胜（隔 0 留 1）
        payload = [
            {"cue": "同名", "channel": 8, "start_ms": 100, "end_ms": 200},
            {"cue": "同名", "channel": 8, "start_ms": 100, "end_ms": 200},
            {"cue": "同名", "channel": 8, "start_ms": 100, "end_ms": 200},
        ]
        body = analyze(web_url, payload).json()
        assert [item["source_index"] for item in body["isolation_plan"]] == [0, 1]
        for item in body["isolation_plan"]:
            assert item["cue"] == "同名"
            assert (item["channel"], item["start_ms"], item["end_ms"]) == (8, 100, 200)

    def test_duration_tiebreak_isolates_shorter_total(self, web_url):
        # 两段互不相连的冲突对，隔离数恒为 2，由隔离总时长决胜：隔两条短的
        payload = [
            {"cue": "长甲", "channel": 1, "start_ms": 0, "end_ms": 100},
            {"cue": "短甲", "channel": 1, "start_ms": 0, "end_ms": 10},
            {"cue": "短乙", "channel": 1, "start_ms": 200, "end_ms": 210},
            {"cue": "长乙", "channel": 1, "start_ms": 200, "end_ms": 300},
        ]
        body = analyze(web_url, payload).json()
        assert [item["source_index"] for item in body["isolation_plan"]] == [1, 2]

    def test_plan_sorted_by_channel_then_index_and_carries_original_interval(self, web_url):
        # 源数组中通道 2 的 cue 在前，输出仍按通道再按下标；每项携带原始区间
        payload = [
            {"cue": "A2", "channel": 2, "start_ms": 0, "end_ms": 10},
            {"cue": "B2", "channel": 2, "start_ms": 5, "end_ms": 15},
            {"cue": "A1", "channel": 1, "start_ms": 0, "end_ms": 10},
            {"cue": "B1", "channel": 1, "start_ms": 5, "end_ms": 15},
        ]
        body = analyze(web_url, payload).json()
        assert body["isolation_plan"] == [
            {"source_index": 2, "cue": "A1", "channel": 1, "start_ms": 0, "end_ms": 10},
            {"source_index": 0, "cue": "A2", "channel": 2, "start_ms": 0, "end_ms": 10},
        ]

    def test_no_conflict_response_has_empty_plan(self, web_url):
        body = analyze(web_url, []).json()
        assert body["isolation_plan"] == []

    def test_422_response_has_no_isolation_plan(self, web_url):
        payload = [{"cue": "A", "channel": 0, "start_ms": 0, "end_ms": 10}]
        resp = analyze(web_url, payload)
        assert resp.status_code == 422
        assert "isolation_plan" not in resp.json()


class TestValidation:
    def test_malformed_json_is_422(self, web_url):
        resp = analyze(web_url, b'[{"cue": "broken", ]')
        assert resp.status_code == 422
        errors = resp.json()["detail"]["errors"]
        assert errors[0]["index"] is None

    def test_non_array_top_level_is_422(self, web_url):
        resp = analyze(web_url, {"cue": "A"})
        assert resp.status_code == 422

    def test_invalid_elements_report_array_indices(self, web_url):
        payload = [
            {"cue": "合法", "channel": 1, "start_ms": 0, "end_ms": 100},
            {"cue": "越界", "channel": 513, "start_ms": 0, "end_ms": 100},
            {"cue": "倒置", "channel": 2, "start_ms": 100, "end_ms": 100},
        ]
        resp = analyze(web_url, payload)
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        indices = {e["index"] for e in detail["errors"]}
        assert indices == {1, 2}
        assert "conflicts" not in resp.json()

    def test_channel_zero_rejected(self, web_url):
        payload = [{"cue": "A", "channel": 0, "start_ms": 0, "end_ms": 10}]
        assert analyze(web_url, payload).status_code == 422

    def test_negative_start_rejected(self, web_url):
        payload = [{"cue": "A", "channel": 1, "start_ms": -1, "end_ms": 10}]
        assert analyze(web_url, payload).status_code == 422

    def test_bool_and_float_fields_rejected(self, web_url):
        payload = [{"cue": "A", "channel": True, "start_ms": 0.5, "end_ms": 10}]
        resp = analyze(web_url, payload)
        assert resp.status_code == 422

    def test_no_partial_results_when_any_element_invalid(self, web_url):
        payload = [
            {"cue": "A", "channel": 1, "start_ms": 0, "end_ms": 100},
            {"cue": "B", "channel": 1, "start_ms": 50, "end_ms": 150},
            {"cue": "坏元素", "channel": "x", "start_ms": 0, "end_ms": 10},
        ]
        resp = analyze(web_url, payload)
        assert resp.status_code == 422
        assert "conflicts" not in resp.json()

    def test_non_utf8_body_is_422(self, web_url):
        resp = analyze(web_url, b'[{"cue": "\xff\xfe", "channel": 1, "start_ms": 0, "end_ms": 1}]')
        assert resp.status_code == 422
