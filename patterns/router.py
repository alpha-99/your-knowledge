#!/usr/bin/env python3
"""Router pattern — two-layer intent classification.

Layer 1: Keyword fast match (zero cost, no LLM).
Layer 2: LLM classification fallback (handles ambiguous queries).

Three intents:
    github_search  — query GitHub Search API via urllib
    knowledge_query — search local knowledge/articles/index.json
    general_chat   — answer directly via LLM

Dependencies: pipeline/model_client.py (quick_chat)
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline.model_client import quick_chat, LLMResponse, Usage

logger = logging.getLogger("router")

_STREAM_HANDLER = logging.StreamHandler(sys.stderr)
_STREAM_HANDLER.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
)
logger.addHandler(_STREAM_HANDLER)
logger.setLevel(logging.INFO)

# ============================================================
# Model client wrappers  (chat -> (text, usage), chat_json -> dict)
# ============================================================


def chat(prompt: str, system: str = "") -> Tuple[str, Tuple[int, int, int]]:
    """Send a one-shot chat request.

    Returns:
        (text_content, (prompt_tokens, completion_tokens, total_tokens))
    """
    response: LLMResponse = quick_chat(prompt, system=system or None)
    u = response.usage
    return response.content, (u.prompt_tokens, u.completion_tokens, u.total_tokens)


def chat_json(prompt: str, system: str = "") -> dict[str, Any]:
    """Send a chat request and parse the response as JSON."""
    text, _ = chat(prompt, system=system)
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}


# ============================================================
# Layer 1: Keyword fast match (zero LLM cost)
# ============================================================

_GITHUB_KEYWORDS = [
    r"github.*(?:搜|找|查|search|find)",
    r"(?:搜|找|查|search|find).*github",
    r"(?:在|用|通过)\s*github",
    r"开源项目.*(?:搜|找|查)",
    r"search.*repo",
    r"fmt:github|github\s+project",
    # Broader project/framework search (no "github" required)
    r"(?:搜索|搜|找|查找|寻找|find|search|推荐).*(?:开源)?\s*(?:项目|框架|仓库|工具|插件|库|repo|framework|tool|library)",
    r"(?:有什么|有哪些|推荐).*(?:开源|github)\s*(?:项目|框架|仓库|工具)",
    r"(?:排行|热门|趋势|popular|trending|top).*(?:开源)?\s*(?:项目|repo|仓库|框架)",
    r"(?:开源|open.source)\s*(?:项目|框架|工具).*(?:推荐|搜索|找|排行)",
]

_KNOWLEDGE_KEYWORDS = [
    r"(?:知识库|knowledge.base)",
    r"(?:本地|内部|已有|我们的).*(?:文章|资料|内容|数据|条目)",
    r"(?:已经|之前).*(?:收集|采集|整理|存储)",
    r"(?:index|索引|已收录|archived|published).*(?:article|文章|条目)",
    r"查查.*(?:资料库|收集|本地)",
    r"(?:what|what's).*(?:collected|stored|indexed|in.*knowledge)",
    r"articles?\s*(?:in|from)\s*(?:our|the|local|knowledge)",
    r"知识库.*(?:有什么|查询|检索|搜索)",
    r"我(?:们)?(?:的|收集|整理).*(?:资料|文章|条目|内容)",
]

_GITHUB_RE = re.compile("|".join(_GITHUB_KEYWORDS), re.IGNORECASE)
_KNOWLEDGE_RE = re.compile("|".join(_KNOWLEDGE_KEYWORDS), re.IGNORECASE)


def _check_github_intent(query: str) -> bool:
    """Check if the query strongly signals a GitHub search intent."""
    return bool(_GITHUB_RE.search(query))


def _check_knowledge_intent(query: str) -> bool:
    """Check if the query strongly signals a knowledge-base query intent."""
    return bool(_KNOWLEDGE_RE.search(query))


def _keyword_classify(query: str) -> str | None:
    """Layer 1: fast keyword-based intent classification.

    Returns:
        'github_search', 'knowledge_query', or None (ambiguous -> fall through).
    """
    github = _check_github_intent(query)
    knowledge = _check_knowledge_intent(query)

    if github and not knowledge:
        return "github_search"
    if knowledge and not github:
        return "knowledge_query"
    return None


# ============================================================
# Layer 2: LLM classification (fallback)
# ============================================================

_CLASSIFY_SYSTEM = """你是一个意图分类器。分析用户输入，判断属于以下哪种意图。

意图定义：
- github_search：用户想在 GitHub 上搜索开源项目/仓库
- knowledge_query：用户想查询本地知识库中已收集整理的文章/资料
- general_chat：普通对话、问答、闲聊，不属于以上两种

返回严格 JSON：
{"intent": "github_search|knowledge_query|general_chat", "reason": "简短原因"}"""


def _llm_classify(query: str) -> str:
    """Layer 2: use LLM to classify ambiguous intent.

    Returns:
        One of 'github_search', 'knowledge_query', 'general_chat'.
    """
    try:
        result = chat_json(query, system=_CLASSIFY_SYSTEM)
        intent = str(result.get("intent", "")).strip().lower()
        if intent in ("github_search", "knowledge_query", "general_chat"):
            logger.info("LLM classified intent: %s", intent)
            return intent
        logger.warning("LLM returned unknown intent '%s', fallback to general_chat", intent)
    except Exception as exc:
        logger.warning("LLM classification failed: %s, fallback to general_chat", exc)
    return "general_chat"


# ============================================================
# Intent classification — two-layer strategy
# ============================================================


def _classify(query: str) -> str:
    """Two-layer intent classification: keyword first, LLM fallback."""
    intent = _keyword_classify(query)
    if intent:
        logger.info("Keyword matched intent: %s", intent)
        return intent
    logger.info("Keyword ambiguous, falling back to LLM classification")
    return _llm_classify(query)


# ============================================================
# Handler: github_search
# ============================================================

_GITHUB_API = "https://api.github.com/search/repositories"


def _extract_search_term(query: str) -> str:
    """Strip intent-signalling phrases to extract the raw search term."""
    term = re.sub(
        r"(?:帮我|请|帮我|帮忙|能不能|可以|想)?"
        r"(?:在|用|通过|到)?\s*"
        r"(?:github|GitHub)\s*"
        r"(?:上|上面)?\s*"
        r"(?:搜索|查找|找一下|找一找|找|查|看看|搜索一下)?\s*[:：]?\s*",
        "",
        query,
        flags=re.IGNORECASE,
    ).strip()
    term = re.sub(r"\s+", " ", term)
    return term if term else query


def _handle_github_search(query: str) -> str:
    """Search GitHub repositories matching the query.

    Uses urllib.request with urllib.parse.quote for parameter encoding.
    """
    term = _extract_search_term(query)
    logger.info("GitHub search term: %s", term)

    params = urllib.parse.urlencode({
        "q": term,
        "sort": "stars",
        "order": "desc",
        "per_page": 10,
    })

    url = f"{_GITHUB_API}?{params}"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "your-knowledge-router/1.0")

    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        req.add_header("Authorization", f"Bearer {github_token}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        logger.error("GitHub API HTTP %d: %s", exc.code, exc.reason)
        return f"GitHub 搜索失败：HTTP {exc.code} {exc.reason}"
    except Exception as exc:
        logger.error("GitHub API request failed: %s", exc)
        return f"GitHub 搜索失败：{exc}"

    items = data.get("items", [])
    if not items:
        return f"未找到与「{term}」相关的 GitHub 仓库。"

    lines = [f"GitHub 搜索「{term}」共 {data.get('total_count', 0)} 个结果，Top {len(items)}："]
    for i, repo in enumerate(items, 1):
        name = repo.get("full_name", "?")
        stars = repo.get("stargazers_count", 0)
        desc = (repo.get("description") or "").strip()
        url_repo = repo.get("html_url", "")
        lang = repo.get("language") or ""
        extra = f" | {lang}" if lang else ""
        lines.append(f"  {i}. {name}  ★{stars}{extra}")
        lines.append(f"     {url_repo}")
        if desc:
            lines.append(f"     {desc[:120]}")

    return "\n".join(lines)


# ============================================================
# Handler: knowledge_query
# ============================================================


_ARTICLES_INDEX = _PROJECT_ROOT / "knowledge" / "articles" / "index.json"


def _load_index() -> list[dict[str, Any]]:
    """Load the knowledge index, returning the article list."""
    if not _ARTICLES_INDEX.exists():
        return []
    try:
        with open(_ARTICLES_INDEX, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("articles", [])
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load knowledge index: %s", exc)
        return []


def _handle_knowledge_query(query: str) -> str:
    """Search local knowledge base for articles matching the query."""
    articles = _load_index()
    if not articles:
        return "本地知识库为空，尚未收录任何文章。"

    keywords = [kw.lower() for kw in re.findall(r"[\w\u4e00-\u9fff]+", query)]

    scored: list[Tuple[int, dict[str, Any]]] = []
    for a in articles:
        title = (a.get("title", "")).lower()
        tags = [t.lower() for t in a.get("tags", [])]
        source = (a.get("source", "")).lower()

        score = 0
        search_text = f"{title} {' '.join(tags)} {source}"
        for kw in keywords:
            if kw in title:
                score += 3
            if kw in tags:
                score += 2
            if kw in search_text:
                score += 1

        if score > 0:
            scored.append((score, a))

    scored.sort(key=lambda x: x[0], reverse=True)

    if not scored:
        return f"知识库中未找到与「{query}」相关的内容。"

    top = scored[:10]
    lines = [
        f"知识库检索「{query}」找到 {len(scored)} 条结果，Top {len(top)}："
    ]
    for i, (score, a) in enumerate(top, 1):
        title = a.get("title", "?")
        src = a.get("source", "?")
        url = a.get("source_url", "")
        rating = a.get("score", 0)
        tags_str = ", ".join(a.get("tags", [])[:4])
        lines.append(f"  {i}. [{src}] {title}  (评分: {rating})")
        lines.append(f"     标签: {tags_str}")
        if url:
            lines.append(f"     {url}")

    return "\n".join(lines)


# ============================================================
# Handler: general_chat
# ============================================================

_CHAT_SYSTEM = (
    "你是一个有帮助的 AI 助手。请简洁直接地回答用户的问题，"
    "使用中文回答（除非用户用英文提问）。"
)


def _handle_general_chat(query: str) -> str:
    """Answer the query directly using LLM."""
    try:
        text, usage = chat(query, system=_CHAT_SYSTEM)
        logger.info(
            "chat usage: prompt=%d completion=%d total=%d",
            usage[0], usage[1], usage[2],
        )
        return text.strip()
    except Exception as exc:
        logger.error("General chat failed: %s", exc)
        return f"抱歉，LLM 调用失败：{exc}"


# ============================================================
# Unified entry point
# ============================================================


def route(query: str) -> str:
    """Route a user query to the appropriate handler.

    Args:
        query: The user's input string.

    Returns:
        The response string from the selected handler.
    """
    if not query or not query.strip():
        return "请输入你的问题。"

    query = query.strip()
    logger.info("Routing query: %s", query[:80])

    intent = _classify(query)

    handlers = {
        "github_search": _handle_github_search,
        "knowledge_query": _handle_knowledge_query,
        "general_chat": _handle_general_chat,
    }

    handler = handlers.get(intent, _handle_general_chat)
    logger.info("Intent=%s -> handler=%s", intent, handler.__name__)

    try:
        return handler(query)
    except Exception as exc:
        logger.exception("Handler %s failed", handler.__name__)
        return f"处理请求时出错：{exc}"


# ============================================================
# Self-test
# ============================================================


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Router — two-layer intent classification → handler dispatch",
    )
    parser.add_argument(
        "query",
        nargs="?",
        help="要路由的查询文本（不提供则运行自检）",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="输出详细日志",
    )
    parser.add_argument(
        "--classify-only",
        action="store_true",
        help="仅输出意图分类结果，不执行 handler",
    )
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.query:
        if args.classify_only:
            intent = _classify(args.query)
            print(intent)
        else:
            result = route(args.query)
            print(result)
    else:
        test_queries = [
            ("在 GitHub 上搜索 AI agent 项目", "github_search"),
            ("帮我找找 GitHub 上的 MCP 相关仓库", "github_search"),
            ("知识库里有哪些关于 agent 的文章", "knowledge_query"),
            ("查询本地已收集的 LLM 相关资料", "knowledge_query"),
            ("你好，今天天气怎么样", "general_chat"),
            ("Python 里的列表和元组有什么区别", "general_chat"),
        ]

        print("=" * 60)
        print("  Router Self-Test")
        print("=" * 60)

        for query, expected in test_queries:
            print(f"\n---\nQuery: {query}")
            print(f"Expected intent: {expected}")

            intent = _classify(query)
            print(f"Classified: {intent}")

            if intent != expected:
                print(f"  WARNING: mismatch! expected={expected} got={intent}")

        print("\n" + "=" * 60)
        print("  End-to-end test")
        print("=" * 60)

        e2e_queries = [
            "在 GitHub 上搜索 openai agents",
            "知识库中有哪些最近的文章",
            "什么是 Python 装饰器",
        ]

        for q in e2e_queries:
            print(f"\n---\nQuery: {q}")
            result = route(q)
            print(result[:500])
