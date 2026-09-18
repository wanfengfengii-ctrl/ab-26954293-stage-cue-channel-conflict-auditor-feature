"""FastAPI 入口：cue 文件冲突分析服务。无持久化，仅内存计算。"""

from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .scanner import scan_conflicts
from .validation import ValidationError, validate_payload

app = FastAPI(title="DMX Cue 冲突分析服务", version="1.0.0")

# 开发期允许 Vite dev server 跨域访问；生产容器内由 web 层 nginx 同源代理 /api。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error_response(message: str, errors: list[ValidationError]) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "message": message,
                "errors": [{"index": e.index, "message": e.message} for e in errors],
            }
        },
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/api/analyze")
async def analyze(request: Request) -> JSONResponse:
    raw = await request.body()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _error_response(
            "文件不是有效的 UTF-8 编码",
            [ValidationError(index=None, message="文件必须是 UTF-8 编码的 JSON 文本")],
        )

    try:
        data = json.loads(
            text,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ValueError(f"非法的 JSON 常量: {constant}")
            ),
        )
    except (json.JSONDecodeError, ValueError) as exc:
        return _error_response(
            "JSON 解析失败",
            [ValidationError(index=None, message=f"JSON 语法错误: {exc}")],
        )

    cues, errors = validate_payload(data)
    if errors:
        return _error_response("cue 文件校验失败", errors)

    report = scan_conflicts(cues)
    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "channels_checked": report.channels_checked,
            "conflict_count": len(report.conflicts),
            "conflicts": [
                {
                    "channel": c.channel,
                    "cue_a": c.cue_a,
                    "cue_b": c.cue_b,
                    "overlap_start_ms": c.overlap_start_ms,
                    "overlap_end_ms": c.overlap_end_ms,
                }
                for c in report.conflicts
            ],
            "contention_windows": [
                {
                    "channel": w.channel,
                    "start_ms": w.start_ms,
                    "end_ms": w.end_ms,
                    "conflict_count": w.conflict_count,
                }
                for w in report.contention_windows
            ],
            "isolation_plan": [
                {
                    "source_index": item.source_index,
                    "cue": item.cue,
                    "channel": item.channel,
                    "start_ms": item.start_ms,
                    "end_ms": item.end_ms,
                }
                for item in report.isolation_plan
            ],
        },
    )
