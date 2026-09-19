# GS1 条码元素串解析 API

基于 Python + FastAPI 的 GS1 元素串（Element String）解析服务。接收含 ASCII 29（GS）分隔符的原始扫描串，按 GS1 规范切分并校验，返回保持原顺序的结构化元素。

## 一键启动

```bash
docker compose up --build
```

启动后访问：

- API 地址： http://localhost:8080/parse
- 交互式文档（Swagger UI）： http://localhost:8080/docs
- 健康检查： http://localhost:8080/health

## 支持的 AI

| AI | 含义 | 长度 | 字符集 | 额外校验 |
|----|------|------|--------|----------|
| 01 | GTIN | 固定 14 位 | 数字 | GS1 Mod-10 校验位 |
| 10 | 批号 BATCH/LOT | 可变 1–20 | GS1 AI 字符集（82 字符） | — |
| 17 | 效期 USE BY OR EXPIRY | 固定 6 位 YYMMDD | 数字 | 真实日期（含闰年），`DD=00` 表示月末 |
| 21 | 序列号 SERIAL | 可变 1–20 | GS1 AI 字符集（82 字符） | — |

解析规则：

- 固定长度字段（01、17）自动定界，无需分隔符（其后若出现分隔符也会被容忍跳过）。
- 可变长度字段（10、21）除位于串末尾外，必须以 ASCII 29（GS）分隔符结束；否则后续数据会被并入该字段。
- 输入不允许以分隔符开头或结尾。
- AI 17 的年份按 GS1 滑动窗口（过去 49 年 / 未来 50 年）确定世纪。

## 接口说明

### POST /parse

请求体（JSON，`data` 为原始扫描串，分隔符写作 ``）：

```bash
curl -X POST http://localhost:8080/parse \
  -H "Content-Type: application/json" \
  -d '{"data": "01095060001343521725123110ABC12321XYZ789"}'
```

成功响应 `200`，元素按原顺序返回，`offset` 为该 AI 在输入中的字节偏移：

```json
{
  "elements": [
    {"ai": "01", "title": "GTIN", "value": "09506000134352", "offset": 0},
    {"ai": "17", "title": "USE BY OR EXPIRY", "value": "251231", "date": "2025-12-31", "offset": 16},
    {"ai": "10", "title": "BATCH/LOT", "value": "ABC123", "offset": 25},
    {"ai": "21", "title": "SERIAL", "value": "XYZ789", "offset": 34}
  ]
}
```

### 错误响应 422

所有解析/校验错误返回 `422`，包含字节偏移 `offset` 与预期规则 `rule`：

```bash
curl -X POST http://localhost:8080/parse \
  -H "Content-Type: application/json" \
  -d '{"data": "0109506000134353"}'
```

```json
{
  "detail": {
    "error": "INVALID_CHECK_DIGIT",
    "message": "GTIN check digit mismatch: expected 2, got 3",
    "offset": 15,
    "rule": "AI (01) GTIN must carry a valid GS1 Mod-10 check digit"
  }
}
```

错误码一览：`EMPTY_INPUT`、`UNKNOWN_AI`、`STRAY_SEPARATOR`、`TRAILING_SEPARATOR`、`TRUNCATED_FIELD`、`INVALID_CHARACTER`、`FIELD_TOO_SHORT`、`FIELD_TOO_LONG`、`INVALID_CHECK_DIGIT`、`INVALID_DATE`。

## 本地开发与测试

```bash
pip install -r requirements-dev.txt
pytest                      # 运行测试
uvicorn app.main:app --port 8080   # 本地起服务
```

## 项目结构

```
app/
  main.py   # FastAPI 路由与错误处理
  gs1.py    # GS1 解析与校验核心
tests/
  test_api.py
Dockerfile
docker-compose.yml
```
