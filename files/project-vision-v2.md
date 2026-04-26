# AI 知识库 —— 产品需求规格说明书 V2.0（终态版）

## 1. 产品愿景

每日定时从 GitHub Trending（AI/ML 分类）、arXiv、Hacker News 三个数据源获取最新信息，经多 Agent 流水线分析处理（摘要总结、归类打标、交叉关联、评级排序），生成一份面向 **LLM 应用开发人员** 的 Markdown 日报，存储在本地。

---

## 2. 目标用户与用户价值

### 2.1 直接用户
- **画像：** LLM 应用开发人员（关注 Agent 框架、RAG、Prompt Engineering、模型推理等方向）
- **痛点：** 每天需要跨多个平台手动追踪 AI 领域最新进展（开源项目、学术论文、社区讨论），信息过载且碎片化
- **价值：** 每天 5 分钟扫读一份精选日报，快速掌握当日关键动态，感兴趣的内容通过链接直达原文

### 2.2 关联角色
- **运维/值班人员：** 接收抓取失败的告警，负责手动介入恢复

---

## 3. 数据源与接入规范

| 数据源 | 接入方式 | 筛选策略 | 每日产出上限 |
|--------|---------|---------|-------------|
| GitHub Trending | 爬取 github.com/trending 页面 + 进入各仓库爬取 README（用于交叉关联） | 只保留 AI/ML 相关分类 | 约 20 条 |
| arXiv | arXiv API 增量抓取（按 submission_date） | 关键词匹配 + 论文热度（引用量） | 约 10 篇 |
| Hacker News | Firebase API（默认热度排序） | 只保留 AI 相关讨论 | 约 10 条 |

**非固定 40 条：** 如果某源筛选后不足上限，按实际数量输出；如果某源筛选后为 0，则该源章节不生成。

### 3.1 GitHub Trending 抓取注意事项
- 每爬取一个仓库页面后，暂停 1 分钟再请求下一个，避免触发 GitHub 限流
- 抓取 README 的目的是提取论文引用信息（arXiv ID），用于后续交叉关联

### 3.2 HN 评论策略
- 每个帖子抓取高赞评论：优先选取点赞数 ≥ 50 的评论，若不足则补至 Top 3
- 每条评论需经 Agent 摘要，输出不超过 200 字

---

## 4. 多 Agent 流水线设计

### 4.1 Agent 角色与职责

```
Fetcher Agent → (JSON) → Summarizer Agent → (JSON) → Recommender Agent → (Markdown)
```

#### 4.1.1 Fetcher Agent
- 负责从三个数据源抓取原始数据
- 输出 JSON 格式的中间产物（只保留最近一次运行，不按日期归档）

Fetcher 输出单条记录字段：

```json
{
  "source": "github | arxiv | hn",
  "source_id": "唯一标识（仓库全名/arXiv ID/HN post ID）",
  "title": "标题",
  "description": "描述/摘要（GitHub: description；arXiv: abstract；HN: 帖子文本）",
  "url": "原文链接",
  "metadata": {
    "github_stars": 0,
    "primary_language": "Python",
    "arxiv_categories": ["cs.AI", "cs.CL"],
    "citation_count": 15,
    "submission_date": "2026-04-24",
    "hn_score": 120,
    "hn_top_comments": [
      {"author": "user1", "text": "原文", "upvotes": 85}
    ],
    "readme_content": "仓库 README 全文（仅 GitHub 源）"
  }
}
```

#### 4.1.2 Summarizer Agent （调 DeepSeek）
- 对每条内容做 **摘要总结**（压缩为 2-3 句）、**归类打标**（标签如 `LLM` `RAG` `Agent` `推理优化` `多模态` 等）
- 追加字段：`summary`、`tags`

#### 4.1.3 Recommender Agent （调 DeepSeek）
- **交叉关联：** 以"末尾相关推荐"区块展示，不合并条目
  - 强关联优先：同项目跨平台（如论文代码正好是 Trending 仓库）
  - 弱关联补充：主题相似（基于关键词匹配 + 标题/摘要 Embedding 相似度）
- **评级排序：** 每个源内部独立排序，不跨源混排
- **跨域高价值捕获：** 非 AI 分类但对 AI 有潜在影响的论文/内容，由 Agent 根据关键词判断，标记为 `跨域·数学` 等标签，放入"值得关注"区块，评级上限 3 星
- 追加字段：`rating`（1-5星）、`related_items`（关联条目 ID 列表）、`is_cross_domain`（布尔值）

---

## 5. 评级公式

各源内部独立排序，按以下公式计算综合评分后排序，再映射为 1-5 星：

### GitHub Trending 源
```
评分 = github_stars(归一化) × 0.50 + agent_relevance × 0.50
```

### arXiv 源
```
评分 = citation_count(归一化) × 0.50 + agent_relevance × 0.50
```

### Hacker News 源
```
评分 = hn_score(归一化) × 0.50 + agent_relevance × 0.50
```

**说明：**
- `agent_relevance` 由 Recommender Agent 基于 LLM 应用开发人员画像给出 0-1 分
- 各源缺失的字段（如论文没有 github_stars）不参与该源的公式计算
- 星级映射：评分前 20% → 5星，20%-40% → 4星，40%-60% → 3星，60%-80% → 2星，后 20% → 1星

---

## 6. 输出规范

### 6.1 存储路径
- `{项目目录}/outputs/{YYYY}/{MM}/{YYYY-MM-DD}.md`
- 历史保留 **30 天**，超过自动删除
- 中间产物 JSON（最近一次运行）存于 `{项目目录}/outputs/latest/`

### 6.2 Markdown 模板

```markdown
# AI 日报 — 2026-04-24

> 📡 数据来源：GitHub Trending (5) · arXiv (8) · Hacker News (6)

---

## 📂 GitHub Trending

### ⭐⭐⭐⭐⭐ [仓库名]
{Summary 摘要} → [GitHub 链接]
`标签1` `标签2`
🔗 **关联推荐：** arXiv《论文标题》

### ⭐⭐⭐⭐ [仓库名]
...

---

## 📄 arXiv 论文精选

### ⭐⭐⭐⭐⭐ [论文标题]
{Summary 摘要} → [arXiv 链接]
`标签1` `标签2`
🔗 **关联推荐：** GitHub《仓库名》· HN 讨论帖《帖子标题》

...

### 🔗 值得关注 —— 跨域内容
### [论文标题]（跨域·数学）
{Summary 摘要} → [arXiv 链接]

---

## 💬 Hacker News 热议

### ⭐⭐⭐⭐⭐ [帖子标题]
{Summary 摘要} → [HN 链接]
`标签1`
💬 **高赞评论摘要：** {评论摘要（≤200字）}
🔗 **关联推荐：** GitHub《仓库名》

...
```

---

## 7. 定时策略

| 项目 | 配置 |
|------|------|
| 执行时间 | 每日 00:00（北京时间） |
| 超时 | 单个 Agent 步骤超过 120 秒视为超时 |
| 重试 | 每个失败步骤最多重试 3 次 |
| 节假日 | 不区分周末和节假日，每天执行 |
| 空数据 | 某源筛选结果为 0 → 该源章节不生成 |
| 全量失败 | 三个源均失败 → 当日不生成报告，发告警 |

---

## 8. 告警机制

以下情况触发告警（通知运维/值班人员人工介入）：
- 任一数据源抓取失败（重试 3 次后仍失败）
- DeepSeek API 连续调用失败
- 流水线执行异常中断

---

## 9. 边缘场景清单

| 场景 | 处理策略 |
|------|---------|
| 同一条内容出现在多个源 | 保留独立条目，不做去重，评分不叠加，通过关联推荐连接 |
| 跨域高价值内容（非 AI 但影响 AI） | Agent 关键字判定，标记 `跨域·XX`，放入"值得关注"区块 |
| 某源筛选后为 0 | 不生成该源章节 |
| 所有源均失败 | 当日不生成报告，告警 |
| GitHub Trending 改版（页面结构变化） | 爬取失败 → 告警，人工修复爬虫 |
| HN 帖子无高赞评论（<50 赞且不足 3 条） | 按实际数量输出，不少于 0 条 |
| arXiv 当日无新论文 | 跳过，不生成 arXiv 章节 |

---

## 10. 技术必要性判断

| 需求 | 是否需要大模型 | 理由 |
|------|--------------|------|
| 数据抓取 | ❌ 规则引擎即可 | HTTP 请求 + HTML 解析 |
| 摘要总结 | ✅ 必须大模型 | 需要语义理解和抽象概括 |
| 归类打标 | ✅ 必须大模型 | 标签体系开放，需理解上下文语义 |
| 交叉关联 | ⚠️ 大模型 + Embedding | 关键词匹配可规则化；语义匹配需 Embedding |
| 评级排序 | ⚠️ 公式可规则化 | 客观指标规则化，agent_relevance 需大模型 |

---

## 11. 核心指标

| 指标 | 定义 | 目标值 | 计算方式 | 数据来源 |
|------|------|--------|---------|---------|
| 报告生成成功率 | 成功生成完整日报的天数 / 总天数 | ≥ 99% | 每日流水线执行日志 | 执行日志 |
| 内容覆盖率 | 三个源均输出的天数 / 总天数 | ≥ 95% | 记录每源是否有有效内容 | 输出统计 |
| 交叉关联准确率 | 人工判定合理的关联数 / 总关联推荐数 | ≥ 80% | 每周抽样审核 | 人工标注 |
| 单次流水线耗时 | Fetcher 触发到 Markdown 写入完成 | ≤ 30 分钟 | 流水线起止时间戳 | 执行日志 |

---

## 12. 技术栈建议

| 组件 | 建议 |
|------|------|
| 抓取（Fetcher） | Python + httpx + BeautifulSoup / Playwright（备选） |
| LLM 调用 | DeepSeek API（OpenAI 兼容接口） |
| Embedding | 可选 sentence-transformers 本地部署 |
| 定时调度 | cron（Linux）或 APScheduler |
| 输出存储 | 本地文件系统 |
| 告警 | 飞书/钉钉/Slack Webhook |
