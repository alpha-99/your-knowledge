# Organizer Archiving & Indexing

- **Issue**: [#3](https://github.com/alpha-99/your-knowledge/issues/3)
- **Type**: AFK
- **Blocked by**: #2

## What to build

实现整理 Agent 的完整归档和索引功能，使其能接收 Analyzer 的分析结果，执行质量门控、去重、格式化归档到 `knowledge/articles/`。

1. 更新 `.opencode/agents/organizer.md`：明确 organizer 接收分析结果的方式（通过上游消息传递），执行以下逻辑：
   - 质量门控：丢弃 score < 6 的条目
   - 去重检查：对比 `knowledge/articles/` 已有条目（按 title + url）
   - 格式化输出：按 `{date}-{source}-{slug}.json` 命名写入 `knowledge/articles/`
   - 更新索引：追加记录到 `knowledge/articles/index.json`
2. 计算 `relevance_score`：结合 score 和标签匹配度，输出 0.0-1.0 的相关度评分
3. 处理边界情况：目标文件已存在时跳过或追加 `-v2`；index.json 不存在时自动创建

## Acceptance criteria

- [ ] 执行 organizer 能成功接收分析数据并写入 `knowledge/articles/` 目录
- [ ] score < 6 的条目被丢弃，不写入任何文件
- [ ] 与历史重复的条目被跳过
- [ ] 文件命名严格遵循 `{date}-{source}-{slug}.json` 格式
- [ ] 每条记录包含 id、title、source、url、collected_at、summary、highlights、score、tags、relevance_score 全部十个字段
- [ ] `knowledge/articles/index.json` 正确更新，包含新条目引用
