"""
工作流节点定义 — 知识库流水线的 5 个核心节点

每个节点是一个纯函数: State → dict（部分状态更新）
LangGraph 会自动将返回值合并到全局 State 中。

节点调用链:
    collect → analyze → organize → review → (conditional) → save
                                     ↑                         │
                                     └── organize (retry) ←────┘ (如果审核未通过)
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from workflows.model_client import accumulate_usage, chat, chat_json
from workflows.state import KBState


# ---------------------------------------------------------------------------
# 节点 1: 采集节点 — 从 GitHub Search API 获取 AI 相关仓库
# ---------------------------------------------------------------------------
def collect_node(state: KBState) -> dict:
    """采集节点：调用 GitHub Search API 搜索 AI/LLM/Agent 相关仓库

    使用 urllib.request 发送请求，获取最近一周更新的高星标仓库。
    网络失败时记录错误但不中断流程。
    """
    print("[Collector] 开始采集...")

    sources: list[dict] = []
    tracker = state.get("cost_tracker", {})

    github_token = os.getenv("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github.v3+json"}
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    one_week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    query = f"ai agent llm stars:>100 pushed:>{one_week_ago}"
    url = f"https://api.github.com/search/repositories?q={urllib.parse.quote(query)}&sort=stars&per_page=10"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        for repo in data.get("items", []):
            sources.append({
                "source": "github",
                "title": repo["full_name"],
                "url": repo["html_url"],
                "description": repo.get("description", ""),
                "stars": repo.get("stargazers_count", 0),
                "language": repo.get("language", ""),
                "collected_at": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as e:
        sources.append({
            "source": "github",
            "title": "[ERROR] GitHub API 请求失败",
            "url": "",
            "description": str(e),
            "stars": 0,
            "language": "",
            "collected_at": datetime.now(timezone.utc).isoformat(),
        })

    print(f"[Collector] 采集到 {len(sources)} 条原始数据")
    return {"sources": sources}


# ---------------------------------------------------------------------------
# 节点 2: 分析节点 — 用 LLM 对每条数据生成中文摘要、标签、评分
# ---------------------------------------------------------------------------
def analyze_node(state: KBState) -> dict:
    """分析节点：对采集到的原始数据逐条调用 LLM 生成分析

    为每条数据生成:
    - summary: 200字以内中文技术摘要
    - tags: 英文标签列表
    - relevance_score: 0.0 - 1.0 相关性评分
    - category: 技术领域分类
    - key_insight: 一句话核心洞察
    """
    print("[Analyzer] 开始分析...")

    sources = state["sources"]
    analyses: list[dict] = []
    tracker = state.get("cost_tracker", {})

    for item in sources:
        if item.get("title", "").startswith("[ERROR]"):
            continue

        prompt = f"""请分析以下技术项目/文章，用 JSON 格式返回：

项目名: {item['title']}
描述: {item.get('description', '无描述')}
来源: {item['source']}
URL: {item.get('url', '')}

请返回以下格式的 JSON:
{{
    "summary": "200字以内的中文技术摘要",
    "tags": ["标签1", "标签2", "标签3"],
    "relevance_score": 0.8,
    "category": "分类（如: llm, agent, rag, tool, framework）",
    "key_insight": "一句话核心洞察"
}}"""

        try:
            result, usage = chat_json(prompt)
            tracker = accumulate_usage(tracker, usage)

            analyses.append({
                **item,
                "summary": result.get("summary", ""),
                "tags": result.get("tags", []),
                "relevance_score": result.get("relevance_score", 0.5),
                "category": result.get("category", "other"),
                "key_insight": result.get("key_insight", ""),
            })
        except Exception as e:
            print(f"[Analyzer] 分析失败: {item['title']} - {e}")
            analyses.append({
                **item,
                "summary": f"分析失败: {e}",
                "tags": [],
                "relevance_score": 0.0,
                "category": "error",
                "key_insight": "",
            })

    print(f"[Analyzer] 完成 {len(analyses)} 条分析")
    return {"analyses": analyses, "cost_tracker": tracker}


# ---------------------------------------------------------------------------
# 节点 3: 整理节点 — 过滤低分条目、按 URL 去重、根据反馈修正
# ---------------------------------------------------------------------------
def organize_node(state: KBState) -> dict:
    """整理节点：将分析结果格式化为标准知识条目

    职责:
    1. 过滤低相关性条目 (relevance_score < 0.6)
    2. 按 URL 去重
    3. 如果有审核反馈且 iteration > 0，调用 LLM 定向修正
    4. 生成统一格式的 articles
    """
    print("[Organizer] 开始整理...")

    analyses = state["analyses"]
    feedback = state.get("review_feedback", "")
    iteration = state.get("iteration", 0)
    tracker = state.get("cost_tracker", {})

    qualified = [a for a in analyses if a.get("relevance_score", 0) >= 0.6]

    seen_urls: set[str] = set()
    unique: list[dict] = []
    for item in qualified:
        url = item.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(item)

    if feedback and iteration > 0:
        print(f"[Organizer] 检测到审核反馈，调用 LLM 进行定向修改 (迭代 {iteration})")
        prompt = f"""你是知识库编辑。以下是审核员的反馈，请据此改进这些知识条目。

审核反馈:
{feedback}

当前条目 (JSON):
{json.dumps(unique, ensure_ascii=False, indent=2)}

请返回改进后的条目列表（JSON 数组），保持相同字段结构。"""

        try:
            improved, usage = chat_json(prompt)
            tracker = accumulate_usage(tracker, usage)
            if isinstance(improved, list):
                unique = improved
        except Exception as e:
            print(f"[Organizer] 根据反馈修正失败: {e}，使用原始数据")

    articles: list[dict] = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for i, item in enumerate(unique):
        articles.append({
            "id": f"{today}-{i:03d}",
            "title": item.get("title", ""),
            "source": item.get("source", "unknown"),
            "url": item.get("url", ""),
            "collected_at": item.get("collected_at", ""),
            "summary": item.get("summary", ""),
            "tags": item.get("tags", []),
            "relevance_score": item.get("relevance_score", 0.5),
            "category": item.get("category", "other"),
            "key_insight": item.get("key_insight", ""),
        })

    print(f"[Organizer] 整理出 {len(articles)} 条知识条目 (迭代 {iteration})")
    return {"articles": articles, "cost_tracker": tracker}


# ---------------------------------------------------------------------------
# 节点 4: 审核节点 — LLM 四维度评分，iteration >= 2 强制通过
# ---------------------------------------------------------------------------
def review_node(state: KBState) -> dict:
    """审核节点：对知识条目进行四维度质量审核

    审核维度 (各 1-5 分):
    1. 摘要质量 — 是否准确、简洁、有洞察
    2. 标签准确性 — 是否与内容匹配
    3. 分类合理性 — 是否归入正确类别
    4. 整体一致性 — 条目之间是否有冲突或重复

    overall_score >= 3.5 → 通过，进入 save
    overall_score < 3.5  → 未通过，回到 organize（最多 3 次迭代）
    iteration >= 2 (第3次) → 强制通过，防止无限循环
    """
    print("[Reviewer] 开始审核...")

    articles = state.get("articles", [])
    iteration = state.get("iteration", 0)
    tracker = state.get("cost_tracker", {})

    if not articles:
        return {
            "review_passed": True,
            "review_feedback": "没有条目需要审核",
            "iteration": iteration + 1,
        }

    prompt = f"""你是知识库质量审核员。请审核以下知识条目：

{json.dumps(articles, ensure_ascii=False, indent=2)}

请按以下维度评估（每项1-5分）：
1. 摘要质量：准确性、简洁性、洞察深度
2. 标签准确性：标签是否与内容匹配
3. 分类合理性：类别是否正确
4. 整体一致性：条目间是否有冲突或冗余

请用 JSON 格式回复：
{{
    "passed": true或false,
    "overall_score": 4.2,
    "feedback": "具体的改进建议（如果不通过）",
    "scores": {{
        "summary_quality": 4,
        "tag_accuracy": 3,
        "category_correctness": 5,
        "consistency": 4
    }}
}}

评分标准：overall_score >= 3.5 即通过。第 {iteration + 1} 次审核（最多3次）。"""

    try:
        result, usage = chat_json(
            prompt,
            system="你是严格但公正的知识库质量审核员。给出具体、可操作的反馈。",
        )
        tracker = accumulate_usage(tracker, usage)

        passed = result.get("passed", False)
        feedback = result.get("feedback", "")
        score = result.get("overall_score", 0)

        if iteration >= 2:
            passed = True
            feedback += "\n[系统] 已达最大审核次数(3次)，强制通过。"

        print(f"[Reviewer] 审核得分: {score}, 通过: {passed} (迭代 {iteration + 1}/3)")

    except Exception as e:
        passed = True
        feedback = f"审核 LLM 调用失败: {e}，自动通过"
        print(f"[Reviewer] 审核失败，自动通过: {e}")

    return {
        "review_passed": passed,
        "review_feedback": feedback,
        "iteration": iteration + 1,
        "cost_tracker": tracker,
    }

# ---------------------------------------------------------------------------
# 节点 4: 审核节点 — 测试模式（模拟审核循环）
# ---------------------------------------------------------------------------
def review_node_test(state: KBState) -> dict:
    """审核节点（测试模式）：模拟审核循环，验证 Review Loop 逻辑

    测试逻辑：
    - iteration 0 (第1次): review_passed=False, 反馈指出摘要质量不足
    - iteration 1 (第2次): review_passed=False, 反馈指出标签不够精确
    - iteration 2 (第3次): review_passed=True,  反馈认可修正结果
    """

    articles = state.get("articles", [])
    iteration = state.get("iteration", 0)

    if not articles:
        return {
            "review_passed": True,
            "review_feedback": "没有条目需要审核",
            "iteration": iteration + 1,
        }

    feedbacks = [
        "TEST-第1次审核（迭代0）：摘要质量不足，缺少核心技术细节。请深入分析技术原理和实现方式。",
        "TEST-第2次审核（迭代1）：标签不够精确，'ai' 过于宽泛。请使用更专业的术语如 'llm-inference'、'multi-agent'。",
        "TEST-第3次审核（迭代2）：修正后质量达标，摘要已包含核心细节，标签专业准确，审核通过。",
    ]

    if iteration >= 2:
        passed = True
    else:
        passed = False

    feedback = feedbacks[min(iteration, 2)]

    print(f"[Reviewer-TEST] iteration={iteration}, review_passed={passed}")

    return {
        "review_passed": passed,
        "review_feedback": feedback,
        "iteration": iteration + 1,
}

# ---------------------------------------------------------------------------
# 节点 5: 保存节点 — 将 articles 写入 knowledge/articles/ 目录
# ---------------------------------------------------------------------------
def save_node(state: KBState) -> dict:
    """保存节点：将通过审核的知识条目写入 JSON 文件

    1. 每篇文章写入 knowledge/articles/{id}.json
    2. 同步更新 knowledge/articles/index.json 索引文件
    3. 输出本次运行总成本
    """
    print("[Saver] 开始保存...")

    articles = state.get("articles", [])
    tracker = state.get("cost_tracker", {})

    if not articles:
        print("[Saver] 没有条目需要保存")
        return {}

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    articles_dir = os.path.join(base_dir, "knowledge", "articles")
    os.makedirs(articles_dir, exist_ok=True)

    saved_files: list[str] = []
    for article in articles:
        filename = f"{article['id']}.json"
        filepath = os.path.join(articles_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(article, f, ensure_ascii=False, indent=2)
        saved_files.append(filename)

    index_path = os.path.join(articles_dir, "index.json")
    index: list[dict] = []
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            try:
                index = json.load(f)
            except json.JSONDecodeError:
                index = []

    existing_ids = {entry["id"] for entry in index}
    for article in articles:
        if article["id"] not in existing_ids:
            index.append({
                "id": article["id"],
                "title": article["title"],
                "category": article.get("category", "other"),
                "relevance_score": article.get("relevance_score", 0.5),
            })

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"[Saver] 保存 {len(saved_files)} 篇文章到 {articles_dir}")
    print(f"[Saver] 本次运行总成本: ¥{tracker.get('total_cost_yuan', 0)}")
    return {}
