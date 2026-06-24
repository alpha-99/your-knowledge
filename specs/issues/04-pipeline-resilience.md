# Pipeline Resilience & Error Handling

- **Issue**: [#4](https://github.com/alpha-99/your-knowledge/issues/4)
- **Type**: HITL
- **Blocked by**: #1, #2, #3

## What to build

解决 PRD 中提出的 4 个开放问题，建立三阶段流水线的容错机制、数据传递协议、重跑策略和进度追踪。

### 1. 数据传递协议

明确 collector → analyzer → organizer 之间如何传递数据：直接读取 `knowledge/raw/` 文件（推荐），还是通过消息体传递含内联 JSON 的消息。

### 2. 上游失败策略

- collector 失败：analyzer 和 organizer 不执行，记录错误日志
- analyzer 部分失败：organizer 处理已成功分析的条目，标记批次为 `partial`
- 超过 30% 条目分析失败时，标记整批次为 `partial` 并记录原因到 `knowledge/raw/errors-{date}.json`

### 3. 重跑/幂等性策略

- 同一日同一数据源已存在原始文件时，collector 跳过（不覆盖）
- analyzer 检查是否已有分析结果，已分析的条目跳过
- organizer 的 Write 逻辑已含去重，无需额外处理
- 支持通过 `--force` 参数强制重新采集

### 4. 进度追踪

- 每次流水线运行记录状态文件 `knowledge/raw/.pipeline-status.json`
- 包含字段：`run_id`、`started_at`、`phase`（collecting/analyzing/organizing/done/failed）、`error`（如失败）、`stats`（collected/analyzed/archived 计数）

## Acceptance criteria

- [ ] 数据传递协议文档化（团队评审确认文件传递方案）
- [ ] collector 失败时，analyzer 和 organizer 被跳过
- [ ] analyzer 部分失败时，organizer 处理成功的部分，标记 partial
- [ ] 重复执行同一天不产生重复条目（幂等性）
- [ ] `knowledge/raw/.pipeline-status.json` 准确记录每次运行状态
- [ ] 错误日志写入 `knowledge/raw/errors-{date}.json`
