"""HTTP API 契约测试：真实请求经由 FastAPI TestClient。"""

import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

VALID_PAYLOAD = [
    {"cue": "开场", "channel": 1, "start_ms": 0, "end_ms": 1000},
    {"cue": "追光", "channel": 1, "start_ms": 500, "end_ms": 1500},
    {"cue": "面光", "channel": 2, "start_ms": 0, "end_ms": 500},
]


def post_raw(body: bytes | str):
    return client.post(
        "/api/analyze",
        content=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )


class TestAnalyzeSuccess:
    def test_conflict_report_shape_and_values(self):
        response = post_raw(json.dumps(VALID_PAYLOAD))
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["channels_checked"] == 2
        assert body["conflict_count"] == 1
        assert body["conflicts"] == [
            {
                "channel": 1,
                "cue_a": "开场",
                "cue_b": "追光",
                "overlap_start_ms": 500,
                "overlap_end_ms": 1000,
            }
        ]
        assert body["contention_windows"] == [
            {"channel": 1, "start_ms": 500, "end_ms": 1000, "conflict_count": 1}
        ]
        # 两条时长相同，隔离源下标更小者
        assert body["isolation_plan"] == [
            {"index": 0, "cue": "开场", "channel": 1, "start_ms": 0, "end_ms": 1000}
        ]

    def test_no_conflict_report(self):
        payload = [
            {"cue": "A", "channel": 1, "start_ms": 0, "end_ms": 100},
            {"cue": "B", "channel": 1, "start_ms": 100, "end_ms": 200},
        ]
        response = post_raw(json.dumps(payload))
        assert response.status_code == 200
        body = response.json()
        assert body["conflicts"] == []
        assert body["conflict_count"] == 0
        assert body["channels_checked"] == 1
        assert body["contention_windows"] == []

    def test_empty_array_is_ok(self):
        response = post_raw("[]")
        assert response.status_code == 200
        body = response.json()
        assert body["channels_checked"] == 0
        assert body["conflicts"] == []
        assert body["contention_windows"] == []

    def test_utf8_chinese_cue_names(self):
        response = post_raw(json.dumps(VALID_PAYLOAD, ensure_ascii=False).encode("utf-8"))
        assert response.status_code == 200
        assert response.json()["conflicts"][0]["cue_a"] == "开场"


class TestContentionWindows:
    def test_chain_merge_across_multiple_conflicts(self):
        # 三条重叠区间链式传递：[10,50)→[40,90)→[80,130) 合并为一个窗口
        payload = [
            {"cue": "A", "channel": 1, "start_ms": 0, "end_ms": 90},
            {"cue": "B", "channel": 1, "start_ms": 10, "end_ms": 50},
            {"cue": "C", "channel": 1, "start_ms": 40, "end_ms": 130},
            {"cue": "D", "channel": 1, "start_ms": 80, "end_ms": 200},
        ]
        response = post_raw(json.dumps(payload))
        assert response.status_code == 200
        body = response.json()
        assert body["conflict_count"] == 5
        assert body["contention_windows"] == [
            {"channel": 1, "start_ms": 10, "end_ms": 130, "conflict_count": 5}
        ]

    def test_touching_windows_merge(self):
        # 冲突重叠区间 [100,150) 与 [150,180) 端点相接，合并为 [100,180)
        payload = [
            {"cue": "A", "channel": 1, "start_ms": 0, "end_ms": 200},
            {"cue": "B", "channel": 1, "start_ms": 100, "end_ms": 150},
            {"cue": "C", "channel": 1, "start_ms": 150, "end_ms": 180},
        ]
        response = post_raw(json.dumps(payload))
        assert response.status_code == 200
        body = response.json()
        assert body["conflict_count"] == 2
        assert body["contention_windows"] == [
            {"channel": 1, "start_ms": 100, "end_ms": 180, "conflict_count": 2}
        ]

    def test_windows_isolated_per_channel_and_sorted(self):
        payload = [
            {"cue": "A", "channel": 2, "start_ms": 0, "end_ms": 100},
            {"cue": "B", "channel": 2, "start_ms": 50, "end_ms": 150},
            {"cue": "C", "channel": 1, "start_ms": 0, "end_ms": 100},
            {"cue": "D", "channel": 1, "start_ms": 50, "end_ms": 150},
            {"cue": "E", "channel": 1, "start_ms": 500, "end_ms": 600},
            {"cue": "F", "channel": 1, "start_ms": 550, "end_ms": 700},
        ]
        response = post_raw(json.dumps(payload))
        assert response.status_code == 200
        assert response.json()["contention_windows"] == [
            {"channel": 1, "start_ms": 50, "end_ms": 100, "conflict_count": 1},
            {"channel": 1, "start_ms": 550, "end_ms": 600, "conflict_count": 1},
            {"channel": 2, "start_ms": 50, "end_ms": 100, "conflict_count": 1},
        ]

    def test_422_response_has_no_windows_and_keeps_detail_shape(self):
        payload = [{"cue": "A", "channel": 999, "start_ms": 0, "end_ms": 100}]
        response = post_raw(json.dumps(payload))
        assert response.status_code == 422
        body = response.json()
        assert set(body.keys()) == {"detail"}
        assert set(body["detail"].keys()) == {"message", "errors"}
        assert body["detail"]["errors"][0]["index"] == 0


class TestIsolationPlan:
    def test_chain_isolates_single_middle_cue(self):
        # 链式重叠：逐冲突任选端点的贪心会隔离两条，全局最优只隔离中间一条
        payload = [
            {"cue": "A", "channel": 1, "start_ms": 0, "end_ms": 10},
            {"cue": "B", "channel": 1, "start_ms": 5, "end_ms": 15},
            {"cue": "C", "channel": 1, "start_ms": 10, "end_ms": 20},
        ]
        response = post_raw(json.dumps(payload))
        assert response.status_code == 200
        body = response.json()
        assert body["conflict_count"] == 2
        assert body["isolation_plan"] == [
            {"index": 1, "cue": "B", "channel": 1, "start_ms": 5, "end_ms": 15}
        ]

    def test_touching_endpoints_coexist_without_isolation(self):
        payload = [
            {"cue": "A", "channel": 1, "start_ms": 0, "end_ms": 100},
            {"cue": "B", "channel": 1, "start_ms": 100, "end_ms": 200},
        ]
        body = post_raw(json.dumps(payload)).json()
        assert body["conflicts"] == []
        assert body["isolation_plan"] == []

    def test_identical_duplicates_isolated_by_source_index(self):
        # 名称与区间完全相同的重复项：隔离源下标更小者
        payload = [
            {"cue": "X", "channel": 1, "start_ms": 0, "end_ms": 100},
            {"cue": "X", "channel": 1, "start_ms": 0, "end_ms": 100},
        ]
        body = post_raw(json.dumps(payload)).json()
        assert body["isolation_plan"] == [
            {"index": 0, "cue": "X", "channel": 1, "start_ms": 0, "end_ms": 100}
        ]

    def test_shorter_isolation_duration_wins(self):
        payload = [
            {"cue": "长渐变", "channel": 1, "start_ms": 0, "end_ms": 100},
            {"cue": "短渐变", "channel": 1, "start_ms": 50, "end_ms": 60},
        ]
        body = post_raw(json.dumps(payload)).json()
        assert body["isolation_plan"] == [
            {"index": 1, "cue": "短渐变", "channel": 1, "start_ms": 50, "end_ms": 60}
        ]

    def test_plan_sorted_by_channel_then_index(self):
        payload = [
            {"cue": "P", "channel": 2, "start_ms": 0, "end_ms": 10},
            {"cue": "Q", "channel": 2, "start_ms": 5, "end_ms": 15},
            {"cue": "R", "channel": 1, "start_ms": 0, "end_ms": 10},
            {"cue": "S", "channel": 1, "start_ms": 5, "end_ms": 15},
        ]
        body = post_raw(json.dumps(payload)).json()
        assert body["isolation_plan"] == [
            {"index": 2, "cue": "R", "channel": 1, "start_ms": 0, "end_ms": 10},
            {"index": 0, "cue": "P", "channel": 2, "start_ms": 0, "end_ms": 10},
        ]

    def test_422_response_has_no_isolation_plan(self):
        payload = [{"cue": "A", "channel": 999, "start_ms": 0, "end_ms": 100}]
        response = post_raw(json.dumps(payload))
        assert response.status_code == 422
        assert "isolation_plan" not in response.json()


class TestAnalyzeRejection:
    def test_malformed_json_is_422(self):
        response = post_raw("[{not json]")
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["errors"][0]["index"] is None

    def test_empty_body_is_422(self):
        response = post_raw("")
        assert response.status_code == 422

    def test_non_utf8_body_is_422(self):
        response = post_raw("[\xff\xfe]".encode("latin-1"))
        assert response.status_code == 422

    def test_non_array_top_level_is_422(self):
        response = post_raw('{"cue": "A"}')
        assert response.status_code == 422
        assert response.json()["detail"]["errors"][0]["index"] is None

    def test_invalid_element_is_422_with_index(self):
        payload = [
            {"cue": "A", "channel": 1, "start_ms": 0, "end_ms": 100},
            {"cue": "B", "channel": 999, "start_ms": 0, "end_ms": 100},
            {"cue": "C", "channel": 2, "start_ms": 50, "end_ms": 50},
        ]
        response = post_raw(json.dumps(payload))
        assert response.status_code == 422
        detail = response.json()["detail"]
        indices = {e["index"] for e in detail["errors"]}
        assert indices == {1, 2}

    def test_no_partial_results_on_error(self):
        # 一个元素合法且互相重叠，但另一个元素非法：整体 422，不给任何分析结果
        payload = [
            {"cue": "A", "channel": 1, "start_ms": 0, "end_ms": 100},
            {"cue": "B", "channel": 1, "start_ms": 50, "end_ms": 150},
            {"cue": "C", "channel": 0, "start_ms": 0, "end_ms": 10},
        ]
        response = post_raw(json.dumps(payload))
        assert response.status_code == 422
        assert "conflicts" not in response.json()

    def test_bool_and_float_fields_rejected(self):
        payload = [{"cue": "A", "channel": True, "start_ms": 0.0, "end_ms": 100}]
        response = post_raw(json.dumps(payload))
        assert response.status_code == 422
        messages = [e["message"] for e in response.json()["detail"]["errors"]]
        assert any("channel" in m for m in messages)
        assert any("start_ms" in m for m in messages)


class TestHealthz:
    def test_healthz(self):
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}
