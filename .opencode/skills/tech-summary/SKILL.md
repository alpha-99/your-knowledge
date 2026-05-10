---
name: tech-summary
description: 当需要对采集的技术内容进行深度分析总结时使用此技能
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# 技术分析总结技能

## 使用场景

当 `knowledge/raw/` 中已有 Collector 采集完成的原始数据，需要逐条深度分析、提炼技术亮点、打分并输出结构化分析结果供 Organizer 整理时，使用此技能。

## 执行步骤

### 第一步：读取最新采集文件

读取 `knowledge/raw/` 目录中最新的采集 JSON 文件。

> 使用 Glob 工具按模式 `knowledge/raw/github-trending-*.json` 或 `knowledge/raw/hackernews-top-*.json` 定位今日待分析的原始数据。

### 第二步：逐条深度分析

对文件中的每个条目，依次完成以下分析维度：

#### 2.1 中文摘要重写

- **长度**：≤ 50 字
- **要求**：覆盖项目/内容的**核心定位 + 关键技术点 + 独特价值**，避免直接翻译原文描述

#### 2.2 技术亮点提炼

- **数量**：2-3 条
- **要求**：用事实说话，每条必须包含具体技术特征或数据（如"支持 x 种模型接入"而非"支持多种模型"）

#### 2.3 质量评分

- **分值**：1-10 分，必须附理由

| 分值 | 含义 | 说明 |
|------|------|------|
| 9-10 | 改变格局 | 突破性技术、重大发布、可能重塑行业方向 |
| 7-8  | 直接有帮助 | 实用工具、高质量教程、可落地的最佳实践 |
| 5-6  | 值得了解 | 有参考价值的新项目、观点文章、技术讨论 |
| 1-4  | 可略过 | 与 AI/LLM/Agent 相关性低、内容浅显或重复 |

> **约束**：同一批次 15 个项目中，评分 9-10 的不超过 2 个。

#### 2.4 标签建议

- **数量**：2-4 个
- **格式**：英文小写，连字符分隔（如 `agent-framework`、`llm-inference`）
- **要求**：与内容强相关，便于检索和分类

### 第三步：趋势发现

汇总分析完所有条目后，从整体视角提炼趋势洞察：

- **共同主题**：识别多条条目共享的技术方向（如 MCP 协议、Agent 编排、本地推理等）
- **新概念 / 新范式**：发现值得关注的新兴术语或方法论

### 第四步：输出分析结果

以 JSON 格式通过返回消息输出分析结果（**不写入文件**，由下游 Organizer 负责持久化）：

```json
{
  "source": "github-trending",
  "skill": "tech-summary",
  "analyzed_at": "YYYY-MM-DDTHH:mm:ssZ",
  "trends": {
    "common_themes": ["agent-framework", "mcp-protocol", "local-inference"],
    "emerging_concepts": ["tool-native agent", "context-compression"]
  },
  "items": [
    {
      "name": "owner/repo",
      "url": "https://github.com/owner/repo",
      "summary": "中文摘要，≤50字",
      "highlights": [
        "亮点一：包含具体技术特征",
        "亮点二：包含可验证的数据或能力"
      ],
      "score": 8,
      "score_reason": "评分理由，说明为什么给这个分值",
      "tags": ["agent", "mcp", "python"]
    }
  ]
}
```

## 注意事项

- **只读原则**：本技能不写入任何文件，分析结果通过返回消息传递。
- **WebFetch 容错**：优先调用 GitHub API（`api.github.com/repos/{owner}/{repo}`）获取项目元数据；API 不可用时回退抓取 HTML 页面。
- **不编造**：所有分析和评价必须基于原文内容与可获取的元数据，不得虚构信息或数据。
- **误差容忍**：单个条目信息不足时，基于已有信息做有限分析并在 `summary` 中注明；超过 30% 条目无法分析时，标记该批次为 `partial` 并说明原因。
- **评分克制**：严格按评分标准给分，9-10 分仅授予真正具有突破性的项目，整批不超过 2 个。
- **亮点可验证**：每条 highlight 须包含具体技术特征，读后可知"这个项目到底强在哪"。

## 输出格式

| 字段 | 类型 | 说明 |
|------|------|------|
| `source` | string | 原始数据来源（如 `"github-trending"`） |
| `skill` | string | 固定值 `"tech-summary"` |
| `analyzed_at` | string | 分析时间，ISO 8601 格式 |
| `trends.common_themes` | string[] | 多条目共享的技术主题 |
| `trends.emerging_concepts` | string[] | 值得关注的新概念 / 新范式 |
| `items[].name` | string | 仓库全名（owner/repo） |
| `items[].url` | string | 仓库 HTML 链接 |
| `items[].summary` | string | 中文摘要（≤50 字） |
| `items[].highlights` | string[] | 2-3 条技术亮点，用事实说话 |
| `items[].score` | number | 质量评分 1-10 |
| `items[].score_reason` | string | 评分理由 |
| `items[].tags` | string[] | 2-4 个英文标签，小写连字符 |
