"""负载校验规则测试。"""

from app.validation import validate_payload


def valid_element(**overrides):
    element = {"cue": "A", "channel": 1, "start_ms": 0, "end_ms": 100}
    element.update(overrides)
    return element


class TestTopLevel:
    def test_object_is_rejected(self):
        _, errors = validate_payload({"cue": "A"})
        assert len(errors) == 1
        assert errors[0].index is None

    def test_scalar_is_rejected(self):
        for bad in ("text", 123, None, True):
            _, errors = validate_payload(bad)
            assert len(errors) == 1
            assert errors[0].index is None

    def test_empty_array_is_valid(self):
        cues, errors = validate_payload([])
        assert cues == []
        assert errors == []


class TestElementShape:
    def test_non_object_element_rejected(self):
        _, errors = validate_payload([["not", "an", "object"]])
        assert [e.index for e in errors] == [0]

    def test_missing_field_rejected(self):
        element = valid_element()
        del element["end_ms"]
        _, errors = validate_payload([element])
        assert len(errors) == 1
        assert "end_ms" in errors[0].message
        assert errors[0].index == 0

    def test_extra_field_rejected(self):
        _, errors = validate_payload([valid_element(note="surprise")])
        assert len(errors) == 1
        assert "note" in errors[0].message


class TestFieldRules:
    def test_cue_must_be_string(self):
        _, errors = validate_payload([valid_element(cue=42)])
        assert len(errors) == 1
        assert "cue" in errors[0].message

    def test_channel_bounds(self):
        assert validate_payload([valid_element(channel=1)])[1] == []
        assert validate_payload([valid_element(channel=512)])[1] == []
        assert validate_payload([valid_element(channel=0)])[1]
        assert validate_payload([valid_element(channel=513)])[1]

    def test_channel_must_be_int_not_bool_or_float(self):
        assert validate_payload([valid_element(channel=True)])[1]
        assert validate_payload([valid_element(channel=1.0)])[1]
        assert validate_payload([valid_element(channel="1")])[1]

    def test_start_ms_must_be_non_negative_int(self):
        assert validate_payload([valid_element(start_ms=-1)])[1]
        assert validate_payload([valid_element(start_ms=0)])[1] == []
        assert validate_payload([valid_element(start_ms=1.5)])[1]
        assert validate_payload([valid_element(start_ms=False)])[1]

    def test_end_ms_must_exceed_start_ms(self):
        assert validate_payload([valid_element(start_ms=100, end_ms=100)])[1]
        assert validate_payload([valid_element(start_ms=100, end_ms=99)])[1]
        assert validate_payload([valid_element(start_ms=100, end_ms=101)])[1] == []

    def test_end_ms_must_be_int(self):
        assert validate_payload([valid_element(end_ms="100")])[1]
        assert validate_payload([valid_element(end_ms=None)])[1]


class TestErrorCollection:
    def test_all_invalid_elements_reported_with_indices(self):
        payload = [
            valid_element(),
            valid_element(channel=0),
            "garbage",
            valid_element(start_ms=5, end_ms=5),
        ]
        _, errors = validate_payload(payload)
        indices = {e.index for e in errors}
        assert indices == {1, 2, 3}

    def test_multiple_errors_on_one_element(self):
        _, errors = validate_payload([valid_element(channel=0, cue=1)])
        assert len(errors) == 2
        assert all(e.index == 0 for e in errors)
