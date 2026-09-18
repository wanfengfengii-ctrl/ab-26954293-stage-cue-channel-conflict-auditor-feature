# 灯光 Cue 冲突检查

舞台监督导入灯光部门 cue 文件时的验收工具：扫描同一 DMX 通道上两两重叠的渐变指令，
在演出前把"抢值"问题退回灯光部门。

- 前端：React + TypeScript（Vite），浏览器上传 UTF-8 JSON，经真实 API 分析
- 后端：FastAPI，负责文件校验与冲突扫描；无持久化，运行时仅 web 与 api 两个服务
- 交付：Docker Compose 一键启动，另含一次性验收服务 `verify`

## 目录结构

```
api/        FastAPI 应用（app/）与 pytest 测试（tests/）
web/        React + TS 前端（Vite），Vitest 组件测试，nginx 同源代理 /api
e2e/        Playwright 端到端测试（打真实运行的栈）
verify/     一次性验收服务：对 compose 网络内真实服务跑 HTTP 验收测试
docker-compose.yml
```

## 快速开始（Docker Compose）

```bash
docker compose up --build
# 前端: http://localhost:8080   API: http://localhost:8000
```

宿主端口由环境变量覆盖：

```bash
WEB_PORT=3000 API_PORT=9000 docker compose up --build
```

## 一键验收（verify 服务）

```bash
docker compose up --build --exit-code-from verify verify
```

`verify` 等待 web/api 健康后，对真实运行的服务发 HTTP 请求跑完整验收
（含经 web 层 nginx 代理的 `/api/analyze` 全链路），跑完即退出，退出码即验收结果。

## cue 文件格式与规则

文件必须是 UTF-8 编码的 JSON 数组，每个元素恰好四个字段：

```json
[
  {"cue": "开场", "channel": 1, "start_ms": 0, "end_ms": 1000},
  {"cue": "追光", "channel": 1, "start_ms": 500, "end_ms": 1500}
]
```

- `cue`：字符串；`channel`：1～512 的整数
- `start_ms`：非负整数；`end_ms`：必须大于 `start_ms` 的整数
- 布尔值、浮点数、缺字段、多字段均视为非法
- 任一元素非法或整份 JSON 非法 → 整体返回 422，不给部分结果

冲突判定：区间一律为左闭右开 `[start_ms, end_ms)`，仅端点相接不算冲突；
重叠段取两起点较大值到两终点较小值；结果按
通道 → 重叠起点 → 重叠终点 → 两个 cue 名字典序排列。

## API 契约

`POST /api/analyze`（请求体为 cue 文件原文，`Content-Type: application/json; charset=utf-8`）

- `200 OK`

```json
{
  "status": "ok",
  "channels_checked": 1,
  "conflict_count": 1,
  "conflicts": [
    {"channel": 1, "cue_a": "开场", "cue_b": "追光", "overlap_start_ms": 500, "overlap_end_ms": 1000}
  ],
  "contention_windows": [
    {"channel": 1, "start_ms": 500, "end_ms": 1000, "conflict_count": 1}
  ]
}
```

`contention_windows` 为抢值时间窗：同一通道内相交或首尾相接（含端点相接）的冲突
重叠区间确定性合并而来，每项含通道、起止毫秒与覆盖的冲突数量，
按通道 → 起点排序；无冲突时为空数组。

- `422`（`index` 为数组下标；整份 JSON 非法时为 `null`）

```json
{
  "detail": {
    "message": "cue 文件校验失败",
    "errors": [{"index": 2, "message": "channel 必须在 1～512 之间"}]
  }
}
```

另有 `GET /healthz` 用于健康检查。

## 本地开发与测试

### API（pytest）

```bash
cd api
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest
uvicorn app.main:app --reload   # http://localhost:8000
```

### 前端（Vitest）

```bash
cd web
npm install
npm test          # Vitest 组件与 API 客户端测试
npm run dev       # http://localhost:5173，/api 自动代理到 localhost:8000
```

### 端到端（Playwright，打真实栈）

```bash
docker compose up -d --build        # 或自行启动 web+api
cd e2e
npm install
npx playwright install chromium
npm test                            # 默认打 http://localhost:8080
# 自定义目标：E2E_BASE_URL=http://localhost:3000 npm test
```
