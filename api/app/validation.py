"""cue 文件负载校验。

规则：
- 顶层必须是 JSON 数组；
- 每个元素必须是对象，且只包含 cue / channel / start_ms / end_ms 四个字段；
- cue 为字符串；channel 为 1～512 的整数；start_ms 为非负整数；end_ms 为大于 start_ms 的整数；
- 布尔值不是合法整数（Python 中 bool 是 int 的子类，需显式排除）。

任一元素非法即整体失败，绝不返回部分结果。
"""

from __future__ import annotations

from dataclasses import dataclass

from .scanner import Cue

REQUIRED_KEYS = ("cue", "channel", "start_ms", "end_ms")
_ALLOWED_KEYS = frozenset(REQUIRED_KEYS)

CHANNEL_MIN = 1
CHANNEL_MAX = 512


@dataclass(frozen=True)
class ValidationError:
    """单条校验错误；index 为数组下标，整体 JSON 非法时为 None。"""

    index: int | None
    message: str


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_element(index: int, element: object) -> tuple[Cue | None, list[ValidationError]]:
    errors: list[ValidationError] = []

    def fail(message: str) -> None:
        errors.append(ValidationError(index=index, message=message))

    if not isinstance(element, dict):
        return None, [
            ValidationError(
                index=index,
                message="元素必须是对象，且包含 cue/channel/start_ms/end_ms 四个字段",
            )
        ]

    keys = set(element)
    missing = [k for k in REQUIRED_KEYS if k not in keys]
    if missing:
        fail(f"缺少字段: {', '.join(missing)}")
    extra = sorted(keys - _ALLOWED_KEYS)
    if extra:
        fail(f"存在未定义字段: {', '.join(extra)}")

    cue = element.get("cue")
    if "cue" in element and not isinstance(cue, str):
        fail("cue 必须是字符串")

    channel = element.get("channel")
    if "channel" in element:
        if not _is_int(channel):
            fail("channel 必须是整数")
        elif not CHANNEL_MIN <= channel <= CHANNEL_MAX:
            fail(f"channel 必须在 {CHANNEL_MIN}～{CHANNEL_MAX} 之间")

    start_ms = element.get("start_ms")
    start_ok = False
    if "start_ms" in element:
        if not _is_int(start_ms):
            fail("start_ms 必须是整数")
        elif start_ms < 0:
            fail("start_ms 必须是非负整数")
        else:
            start_ok = True

    end_ms = element.get("end_ms")
    end_ok = False
    if "end_ms" in element:
        if not _is_int(end_ms):
            fail("end_ms 必须是整数")
        else:
            end_ok = True

    if start_ok and end_ok and end_ms <= start_ms:
        fail("end_ms 必须大于 start_ms")

    if errors:
        return None, errors
    return Cue(cue=cue, channel=channel, start_ms=start_ms, end_ms=end_ms), []


def validate_payload(data: object) -> tuple[list[Cue], list[ValidationError]]:
    """校验整份负载。返回 (合法 cue 列表, 错误列表)；有错时调用方必须整体拒绝。"""
    if not isinstance(data, list):
        return [], [ValidationError(index=None, message="顶层必须是 JSON 数组")]

    cues: list[Cue] = []
    errors: list[ValidationError] = []
    for index, element in enumerate(data):
        cue, element_errors = _validate_element(index, element)
        errors.extend(element_errors)
        if cue is not None:
            cues.append(cue)
    return cues, errors
