---
name: github-trending
description: 当需要采集 GitHub 热门开源项目时使用此技能。适用于知识库采集阶段。
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# GitHub Trending 采集技能

## 使用场景

当需要从 GitHub 采集当日热门 AI/LLM/Agent 领域的开源项目，生成结构化 JSON 数据供后续分析和整理时，使用此技能。

## 执行步骤

### 第一步：搜索热门仓库

通过 GitHub Search API 搜索近 7 天内创建的、与 AI/LLM/Agent 相关的仓库，按 stars 数降序排列。

> 搜索端点：`GET /search/repositories`
> 建议查询参数：`q=ai+llm+agent+created:>={7天前日期}&sort=stars&order=desc&per_page=100`

### 第二步：提取信息

从 API 返回结果中提取每个仓库的以下字段：

- `name` — 仓库全名（owner/repo）
- `url` — 仓库 HTML 地址
- `stars` — 当前 star 数量
- `language` — 主要编程语言
- `topics` — 仓库主题标签列表
- `description` — 仓库描述文本

### 第三步：过滤

纳入与 AI/LLM/Agent 直接相关的项目，排除以下内容：

- Awesome 列表类仓库（如 `awesome-*`、`awesome-*-list`）
- 纯教程 / 课程笔记仓库
- 与 AI/LLM/Agent 领域无关的通用工具
- 仅有 README 无代码的展示性仓库
- Star 刷量
- 无 README

### 第四步：去重

对比 `knowledge/raw/` 目录中历史采集记录，移除已在往期出现的同名仓库，避免重复收录。

> 使用 Glob 工具扫描 `knowledge/raw/github-trending-*.json` 获取历史记录。

### 第五步：撰写中文摘要

为每个通过过滤的仓库生成一段中文摘要，公式：

> **{项目名}** + **{用一句话描述它做什么}** + **{为什么值得关注}**

要求：
- 摘要长度控制在 40–80 字
- 突出与 AI/LLM/Agent 的关联性
- 避免直接翻译英文描述，需重新组织语言

### 第六步：排序取 Top 15

按 `stars` 数从高到低排序，取前 15 个条目。若有效条目不足 15 个，则以实际数量为准。

### 第七步：输出 JSON

将结果写入 `knowledge/raw/github-trending-YYYY-MM-DD.json`（日期替换为当天日期）。

```json
{
  "source": "github-trending",
  "skill": "github-trending",
  "collect_at": "YYYY-MM-DDTHH:mm:ssZ",
  "items": [
    {
      "name": "owner/repo",
      "url": "https://github.com/owner/repo",
      "summary": "中文摘要，40-80字",
      "stars": 1234,
      "language": "Python",
      "topics": ["agent", "llm", "mcp"]
    }
  ]
}
```

## 注意事项

- **API 限流**：GitHub Search API 未认证时限制 10 次/分钟，认证后 30 次/分钟。遇到限流需等待后重试，最多 3 次。
- **日期处理**：所有日期使用 ISO 8601 格式，时区为 UTC。
- **字符编码**：输出 JSON 文件必须使用 UTF-8 编码。
- **缩进格式**：JSON 使用 2 空格缩进。
- **误差容忍**：单个仓库信息不完整时跳过该条目，不中断整体流程。异常条目写入 `knowledge/raw/errors-{date}.json`。
- **幂等性**：如果当日 JSON 文件已存在，需合并去重，不覆盖已有数据。
- **要求**：摘要必须是中文和不编造不存在的仓库

## 输出格式

| 字段 | 类型 | 说明 |
|------|------|------|
| `source` | string | 固定值 `"github-trending"` |
| `skill` | string | 固定值 `"github-trending"` |
| `collect_at` | string | 采集时间，ISO 8601 格式 |
| `items[].name` | string | 仓库全名（owner/repo） |
| `items[].url` | string | 仓库 HTML 链接 |
| `items[].summary` | string | 中文摘要（40–80 字） |
| `items[].stars` | number | star 数量 |
| `items[].language` | string | 主要编程语言 |
| `items[].topics` | string[] | 主题标签列表 |
