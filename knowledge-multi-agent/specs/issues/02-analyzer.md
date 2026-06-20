# Analyzer Skill & Analysis Pipeline

- **Issue**: [#2](https://github.com/alpha-99/your-knowledge/issues/2)
- **Type**: AFK
- **Blocked by**: #1

## What to build

实现分析技能和分析 Agent 的完整链路，使 analyzer 能从 `knowledge/raw/` 读取采集数据，对每条内容进行深度分析并输出三维度标签。

1. 编写 `.opencode/skills/tech-summary/SKILL.md`：定义技术摘要分析工作流——读取项目元数据、撰写中文摘要（2-3 句）、提炼亮点（1-2 条）、质量评分（1-10）、推荐标签（2-4 个英文小写连字符）
2. 更新 `.opencode/agents/analyzer.md`：明确 analyzer 从 `knowledge/raw/` 读取指定日期的 JSON，逐条分析后通过返回消息向下游传递分析结果（保持只读原则）
3. 分析输出格式：在原始字段基础上新增 `highlights`（string[]）、`score`（number 1-10）、`tags`（string[] 2-4 个英文小写连字符）

## Acceptance criteria

- [ ] `tech-summary/SKILL.md` 包含完整的分析流程（读取 → 获取上下文 → 摘要 → 亮点 → 评分 → 标签）
- [ ] 执行 `@analyzer knowledge/raw/github-trending-{date}.json` 能对每条原始数据产出新增三个维度的分析结果
- [ ] highlights 每条 1-2 点，中文，具体可验证
- [ ] score 严格按 1-10 评分标准，≥ 1 且 ≤ 10
- [ ] tags 全英文小写、连字符分隔、与内容强相关
- [ ] 不编造信息，所有分析基于原文内容
