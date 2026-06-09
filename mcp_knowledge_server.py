#!/usr/bin/env python3
"""MCP Server — 本地知识库搜索服务 (JSON-RPC 2.0 over stdio).

提供 3 个 MCP 工具:
  - search_articles: 按关键词搜索文章标题和摘要
  - get_article:     按 ID 获取文章完整内容
  - knowledge_stats: 返回统计信息（总数、来源分布、热门标签）

用法:
    python3 pipeline/mcp_knowledge_server.py
    # 或通过 MCP Client 配置启动
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DIR = PROJECT_ROOT / "knowledge" / "articles"

SERVER_NAME = "knowledge-base"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"


def log(msg: str) -> None:
    print(f"[mcp-server] {msg}", file=sys.stderr, flush=True)


def _load_articles() -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    if not ARTICLES_DIR.exists():
        log(f"Articles directory not found: {ARTICLES_DIR}")
        return articles

    for fpath in sorted(ARTICLES_DIR.glob("*.json")):
        if fpath.name == "index.json":
            continue
        try:
            with open(fpath, encoding="utf-8") as f:
                article = json.load(f)
                if isinstance(article, dict) and "id" in article:
                    articles.append(article)
        except (json.JSONDecodeError, OSError) as exc:
            log(f"Skip invalid file {fpath.name}: {exc}")

    log(f"Loaded {len(articles)} articles from {ARTICLES_DIR}")
    return articles


def _make_response(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _make_error(req_id: Any | None, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _tool_result(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


# ── Tool Implementations ─────────────────────────────────────────────────


def search_articles(articles: list[dict[str, Any]], keyword: str, limit: int = 5) -> str:
    keyword_lower = keyword.lower()
    scored: list[tuple[int, dict[str, Any]]] = []

    for a in articles:
        title = (a.get("title") or "").lower()
        summary = (a.get("summary") or "").lower()
        tags = " ".join(a.get("tags", [])).lower()

        if keyword_lower in title or keyword_lower in summary:
            score = 0
            score += title.count(keyword_lower) * 10
            score += summary.count(keyword_lower) * 3
            score += tags.count(keyword_lower) * 5
            scored.append((score, a))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = scored[:limit]

    if not results:
        return f"未找到与 '{keyword}' 相关的文章。"

    lines = [f"搜索 '{keyword}' 找到 {len(scored)} 篇（显示前 {len(results)} 篇）:\n"]
    for i, (s, a) in enumerate(results, 1):
        lines.append(
            f"  {i}. [{a.get('id')}] {a.get('title', '?')}"
            f"  (score={a.get('score', '?')}, tags={a.get('tags', [])})"
        )
        lines.append(f"     {a.get('summary', '')[:120]}")
    return "\n".join(lines)


def get_article(articles: list[dict[str, Any]], article_id: str) -> str:
    for a in articles:
        if a.get("id") == article_id:
            return json.dumps(a, ensure_ascii=False, indent=2)
    return f"未找到 ID 为 '{article_id}' 的文章。"


def knowledge_stats(articles: list[dict[str, Any]]) -> str:
    total = len(articles)
    if total == 0:
        return "知识库为空，暂无统计数据。"

    sources = Counter(a.get("source", "unknown") for a in articles)
    statuses = Counter(a.get("status", "unknown") for a in articles)
    all_tags: Counter[str] = Counter()
    for a in articles:
        for tag in a.get("tags", []):
            if tag:
                all_tags[tag] += 1

    avg_score = sum(a.get("score", 0) for a in articles) / total if total else 0

    lines = [
        f"知识库统计:",
        f"  文章总数: {total}",
        f"  平均评分: {avg_score:.1f}",
        f"",
        f"  来源分布:",
    ]
    for src, cnt in sources.most_common():
        lines.append(f"    {src}: {cnt}")

    lines.append("")
    lines.append(f"  状态分布:")
    for st, cnt in statuses.most_common():
        lines.append(f"    {st}: {cnt}")

    lines.append("")
    lines.append(f"  热门标签 (Top 10):")
    for tag, cnt in all_tags.most_common(10):
        lines.append(f"    {tag}: {cnt}")

    return "\n".join(lines)


# ── Request Dispatch ─────────────────────────────────────────────────────


def _handle_initialize(params: dict[str, Any], req_id: Any) -> dict[str, Any]:
    log(f"initialize  client={params.get('clientInfo', {}).get('name', '?')}")
    return _make_response(req_id, {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    })


def _handle_tools_list(req_id: Any) -> dict[str, Any]:
    tools = [
        {
            "name": "search_articles",
            "description": "按关键词搜索知识库文章，匹配标题和摘要。返回匹配的文章ID、标题、评分和摘要。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词，支持英文/中文",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量上限（默认 5）",
                        "default": 5,
                    },
                },
                "required": ["keyword"],
            },
        },
        {
            "name": "get_article",
            "description": "按文章ID获取完整内容（JSON 格式），包含摘要、标签、亮点、来源URL等全部字段。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "article_id": {
                        "type": "string",
                        "description": "文章唯一ID，格式如 github-20260608-001",
                    },
                },
                "required": ["article_id"],
            },
        },
        {
            "name": "knowledge_stats",
            "description": "返回知识库统计信息：文章总数、来源分布、状态分布、热门标签 Top 10。",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
    ]
    return _make_response(req_id, {"tools": tools})


def _handle_tools_call(params: dict[str, Any], req_id: Any, articles: list[dict[str, Any]]) -> dict[str, Any]:
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    log(f"tools/call  {tool_name}  args={arguments}")

    try:
        if tool_name == "search_articles":
            keyword = str(arguments.get("keyword", ""))
            limit = int(arguments.get("limit", 5))
            result_text = search_articles(articles, keyword, limit)
        elif tool_name == "get_article":
            article_id = str(arguments.get("article_id", ""))
            result_text = get_article(articles, article_id)
        elif tool_name == "knowledge_stats":
            result_text = knowledge_stats(articles)
        else:
            return _make_error(req_id, -32601, f"Method not found: {tool_name}")

        return _make_response(req_id, _tool_result(result_text))
    except Exception as exc:
        log(f"Tool error: {exc}")
        return _make_error(req_id, -32603, f"Tool execution error: {exc}")


def dispatch(request: dict[str, Any], articles: list[dict[str, Any]]) -> dict[str, Any] | None:
    method = request.get("method", "")
    req_id = request.get("id")
    params: dict[str, Any] = request.get("params", {})

    # Notifications — no response
    if req_id is None:
        if method == "notifications/initialized":
            log("received notifications/initialized")
        return None

    if method == "initialize":
        return _handle_initialize(params, req_id)
    elif method == "tools/list":
        return _handle_tools_list(req_id)
    elif method == "tools/call":
        return _handle_tools_call(params, req_id, articles)
    else:
        return _make_error(req_id, -32601, f"Method not found: {method}")


def main() -> None:
    log(f"Starting {SERVER_NAME} v{SERVER_VERSION}  protocol={PROTOCOL_VERSION}")
    log(f"Articles directory: {ARTICLES_DIR}")

    articles = _load_articles()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            log(f"Invalid JSON: {exc}")
            continue

        response = dispatch(request, articles)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
