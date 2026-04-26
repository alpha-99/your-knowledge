# AI 知识库 · 项目愿景 v1.0

## 概述

每日 00:00（北京时间）自动运行的批处理 pipeline，从三源抓取 AI 相关内容，经多 Agent 流水线处理后输出一份 Markdown 日报，保存到本地文件系统。

---

## 数据源

| 源 | 获取方式 | 每日上限 | 筛选条件 |
|---|---|---|---|
| GitHub Trending | 抓取 `github.com/trending` 页面 + 逐 repo README（间隔 60s） | 最多 20 条 | Topics 包含 ai/llm/agent 之一 + Agent 根据 README 二次判断；实际产出按当日实有数量 |
| arXiv | arXiv API 增量查（按 `submission_date`） | 最多 50 条 | 分类限 `cs.AI`、`cs.CL`、`cs.LG` |
| Hacker News | Firebase API 取 Top 50（按 score 降序） | 最多 50 条 | 仅 AI 相关讨论 |

若某源筛后产出为 0，该板块跳过。不硬凑数量。

---

## 固定标签体系

- Agent
- RAG
- LLM
- 推理优化
- 多模态
- 模型部署 / 推理引擎
- AI Infra / 训练框架
- AI 编程工具
- 评估 / 安全 / 对齐
- 跨领域

---

## Pipeline 流程

```
Collector → Analyzer → Organizer
```

### Collector（采集）
- 三源各自独立抓取
- 统一输出 JSON schema 到 `outputs/latest/collector_output.json`

### Analyzer（分析，调用 DeepSeek）
- 每条产出 **80~120 字摘要**
- 从固定分类中打标签（允许多标签）
- 追加字段 `summary`、`tags`
- 输出到 `outputs/latest/analyzer_output.json`

### Organizer（整理，调用 DeepSeek）
- 每条按 **GitHub Stars**（数值降序）排序
- 三源独立排序，不混合
- 追加字段 `rating`（1-5★ star 分档）

---

## 不做什么

- 不做用户注册 / 登录 / 个人化推荐
- 不做 Web UI / API Server / 数据库
- 不做实时推送
- 不归档每日原始 JSON 快照（只保留 `outputs/latest/` 下最新一次中间结果）
- 不做全文翻译
- 不做多渠道分发（仅本地文件）

---

## 输出规范

### 中间 JSON
- 路径：`outputs/latest/`
- 保留最新一次运行结果，不按日期归档

### 最终 Markdown 报告
- 路径：`outputs/{YYYY}/{MM}/{YYYY-MM-DD}.md`
- 仅保留最近 30 天，更早的自动删除
- 模板结构：每日报头 → GitHub Trending 板块（按 rating 降序）→ arXiv 论文板块 → Hacker News 热议板块

---

## 验收标准

| 维度 | 要求 |
|---|---|
| 摘要长度 | 每篇 80~120 字（硬校验），超出范围则标记并重新生成 |
| 标签准确性 | 允许按条目数计 10% 误差（即 20 条中最多 2 条标签有误） |
| 排序正确性 | Star 数值排序客观可验证，无需人工评判 |
| 覆盖率 | 不做硬性要求——某源当天无产出则跳过该板块 |
| 验证方式 | 先手动运行观察一星期，后续再补自动化测试 |

---

## 运行保障

| 规则 | 值 |
|---|---|
| 调度 | Cron 每日 00:00 北京时间 |
| 单步超时 | 120 秒 |
| 失败重试 | 最多 3 次 |
| 空源处理 | 跳过该板块 |
| 全源失败 | 不发报告，触发告警 |
| 告警方式 | Webhook（Feishu / DingTalk / Slack） |

---

## 技术栈

| 组件 | 选型 |
|---|---|
| 抓取 | Python + httpx + BeautifulSoup |
| 回退渲染 | Playwright（当静态请求失败时） |
| LLM | DeepSeek API（OpenAI 兼容） |
| 调度 | cron |
| 存储 | 本地文件系统 |
| 告警 | Webhook |
