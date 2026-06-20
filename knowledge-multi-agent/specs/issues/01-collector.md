# Collector Skill & Raw Data Layer

- **Issue**: [#1](https://github.com/alpha-99/your-knowledge/issues/1)
- **Type**: AFK
- **Blocked by**: None

## What to build

完成 GitHub Trending 采集技能的完整实现，打通 collector → knowledge/raw/ 的数据落盘链路。

1. 编写 `.opencode/skills/github-trending/SKILL.md`：定义从 GitHub Trending 页面抓取 Top 50、过滤 AI 相关（LLM/Agent）条目、按热度排序的完整工作流
2. 更新 `.opencode/agents/collector.md`：将 Write 权限加入允许列表（仅限 `knowledge/raw/` 目录），使 collector 能够将筛选后的数据持久化为 `knowledge/raw/github-trending-{YYYY-MM-DD}.json`
3. 定义 Raw JSON Schema：每条数据包含 `title`、`url`、`source`、`popularity`、`summary` 五个必填字段

## Acceptance criteria

- [ ] `github-trending/SKILL.md` 包含完整的采集步骤（抓取 → 过滤 → 排序 → 输出）
- [ ] `collector.md` 已更新权限声明，允许 Write 到 `knowledge/raw/`
- [ ] 执行 `@collector 采集今天的 GitHub Trending` 能产出 `knowledge/raw/github-trending-{today}.json`
- [ ] 产出的 JSON 全部字段完整，热度 ≥ 50，条目数 ≥ 10
- [ ] 重复执行同一天不产生重复条目
