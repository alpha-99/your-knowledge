# AGENTS.md — AI 知识库助手

## 📋 项目概述

自动化采集 GitHub Trending 与 Hacker News 上 AI/LLM/Agent 领域的技术动态，通过 AI 分析提炼、结构化存储为 JSON 知识条目，并支持多渠道（Telegram/飞书）分发的智能知识库助手。

## 🛠 技术栈

| 层级 | 技术 |
|------|------|
| 语言 | Python 3.12+ |
| AI 框架 | OpenCode + 国产大模型 |
| 工作流 | LangGraph |
| 采集引擎 | OpenClaw |
| 依赖管理：pip + requirements.txt
| 版本控制：Git

## 📐 编码规范

- **风格**: PEP 8
- **命名**: `snake_case`（变量、函数、方法、文件名）
- **类型注解**: 所有函数参数和返回值必须标注类型
- **文档字符串**: Google 风格 docstring
- **日志**: 禁止裸 `print()`，统一使用 `logging` 模块
- **导入顺序**: 标准库 → 第三方库 → 项目内部模块，每组间空一行
- **行宽**: 88 字符（兼容 Black 格式化）
- **禁止** import *
- **文件编码统一** UTF-8

## 📁 项目结构
```
your-knowledge/
├── AGENTS.md                  — 项目规范（本文件）
├── opencode.json              — OpenCode 配置
├── .opencode/
│   ├── agents/                — Agent 角色定义文件
│   │   ├── collector.md
│   │   ├── analyzer.md
│   │   └── organizer.md
│   └── skills/                — 可复用技能包
│       ├── github-trending/SKILL.md
│       └── tech-summary/SKILL.md
├── knowledge/
│   ├── raw/                   — 原始采集数据（JSON）
│   └── articles/              — 结构化知识条目（JSON）
├── pipeline/                  — 自动化流水线（Week 2）
├── workflows/                 — LangGraph 工作流（Week 3）
└── openclaw/                  — OpenClaw 部署配置（Week 4）
```
## 内容规范
- 摘要语言: 中文
- 摘要长度: 不超过 100 字
- 技术术语保留英文原文（如 LangGraph、Agent、Token）
- 评分标准: 1-10 分，9-10 改变格局，7-8 直接有帮助，5-6 值得了解

## 📄 知识条目 JSON 格式
每条知识以 JSON 文件存储在 `knowledge/articles/` 目录下：
```json
{
  "id": "uuid-v7",
  "title": "文章标题",
  "source": "github_trending|hacker_news",
  "source_url": "https://...",
  "summary": "AI 生成的摘要（200 字内）",
  "content_hash": "sha256",
  "tags": ["AI", "LLM", "Agent"],
  "collection_status": "collected|analyzed|published",
  "published_at": "2026-04-26T00:00:00+08:00",
  "collected_at": "2026-04-26T00:00:00+08:00",
  "analyzed_at": null
}
```
**必填字段**：id, title, source_url, summary, tags, status
**status 可选值**：draft / reviewed / published

## 🤖 Agent 角色概览

| 角色 | 职责 | 输入 → 输出 | 工具 |
|------|------|-------------|------|
| **Collector** | 定时采集 GitHub Trending / Hacker News 原始数据 | 爬虫 → `knowledge/raw/*.json` | OpenClaw |
| **Analyzer** | AI 分析、摘要、打标签、结构化 | `raw/*.json` → `articles/*.json` | LLM (OpenCode) |
| **Organizer** | 质检、去重、分发到 Telegram / 飞书 | `articles/*.json` → 渠道消息 | LangGraph 工作流 |

工作流：`Collector → LangGraph Orchestrator → Analyzer → Organizer`

## 🚫 红线（绝对禁止）

1. **禁止泄露密钥** — API Key、Token、密码等不得硬编码或提交到仓库
2. **禁止跳过代码审查** — 所有修改必须经过 PR review，禁止直接 push 到 main
3. **禁止操作生产数据** — 未经授权不得修改/删除生产环境的 `knowledge/` 数据
4. **禁止绕过限流** — 采集时不得移除 rate limit、不得伪造 User-Agent 绕过反爬
5. **禁止引入未经审查的依赖** — 所有第三方库必须经过安全评估
6. **禁止手动干预工作流** — Agent 工作流由 LangGraph 编排，不得手动修改中间状态
7. **不编造不存在的项目或数据**
8. **不执行 rm -rf 等危险命令**
9. **不修改 AGENTS.md 本身（除非明确要求）**

