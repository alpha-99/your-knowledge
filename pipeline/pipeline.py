#!/usr/bin/env python3
"""四步知识库自动化流水线。

步骤:
  1. Collect  — 从 GitHub Search API 和 RSS 源采集 AI 相关内容
  2. Analyze  — 调用 LLM 对每条内容进行摘要/评分/标签分析
  3. Organize — 去重 + 格式标准化 + 校验
  4. Save     — 将文章保存为独立 JSON 文件到 knowledge/articles/

用法:
    python pipeline/pipeline.py --sources github,rss --limit 20
    python pipeline/pipeline.py --sources github --limit 5
    python pipeline/pipeline.py --sources rss --limit 10
    python pipeline/pipeline.py --sources github --limit 5 --dry-run
    python pipeline/pipeline.py --verbose
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import textwrap
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

import httpx
import yaml

from model_client import create_provider, chat_with_retry

# ============================================================================
# Logging
# ============================================================================

logger = logging.getLogger("pipeline")

_STREAM_HANDLER = logging.StreamHandler(sys.stderr)
_STREAM_HANDLER.setFormatter(
    logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
    )
)
logger.addHandler(_STREAM_HANDLER)
logger.setLevel(logging.INFO)

# ============================================================================
# Constants
# ============================================================================

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_RAW_DIR = _PROJECT_ROOT / "knowledge" / "raw"
_ARTICLES_DIR = _PROJECT_ROOT / "knowledge" / "articles"
_INDEX_FILE = _ARTICLES_DIR / "index.json"

_GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"

_RSS_SOURCES_FILE = _PROJECT_ROOT / "pipeline" / "rss_sources.yaml"

_RSS_MAX_PER_FEED = 15
_RSS_FETCH_TIMEOUT = 20.0


def _load_rss_sources() -> list[dict[str, Any]]:
    """Load enabled RSS sources from ``rss_sources.yaml``."""
    if not _RSS_SOURCES_FILE.exists():
        logger.warning("RSS sources file not found: %s", _RSS_SOURCES_FILE)
        return []
    with open(_RSS_SOURCES_FILE, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    sources = data.get("sources", []) if data else []
    enabled = [s for s in sources if s.get("enabled", True)]
    logger.info("Loaded %d RSS sources (%d enabled)", len(sources), len(enabled))
    return enabled

_GITHUB_FETCH_TIMEOUT = 30.0

_DEFAULT_SINCE_DAYS = 7
_DEFAULT_LIMIT = 20

_AI_KEYWORDS: list[str] = [
    r"\bai\b",
    r"\bllm\b",
    r"\bagent\b",
    r"\bmachine.learning\b",
    r"\bdeep.learning\b",
    r"\bneural.network\b",
    r"\btransformer\b",
    r"\brag\b",
    r"\bprompt\b",
    r"\bfine.tun",
    r"\bembedding\b",
    r"\bopenai\b",
    r"\banthropic\b",
    r"\bgpt\b",
    r"\bclaude\b",
    r"\bgemini\b",
    r"\bllama\b",
    r"\bdeepseek\b",
    r"\bqwen\b",
    r"\bmcp\b",
    r"\binference\b",
    r"\btraining\b",
    r"\breinforcement.learning\b",
    r"\bgenerative\b",
    r"\bdiffusion\b",
    r"\blangchain\b",
]
_AI_KEYWORD_RE = re.compile("|".join(_AI_KEYWORDS), re.IGNORECASE)

_VALID_STATUSES = {"draft", "review", "published", "archived"}
_VALID_AUDIENCES = {"beginner", "intermediate", "advanced"}

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*-\d{8}-\d{3}$")

_HTTP_ERRORS: tuple[type[Exception], ...] = (
    httpx.HTTPStatusError,
    httpx.RequestError,
    httpx.TimeoutException,
)

# ============================================================================
# Helpers
# ============================================================================



def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_str() -> str:
    return date.today().isoformat()


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path) -> dict[str, Any] | list[Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: Any) -> None:
    _ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("Saved  %s", path)


def _is_ai_related(title: str, description: str = "") -> bool:
    text = f"{title} {description}"
    return bool(_AI_KEYWORD_RE.search(text))


def _strip_html(text: str) -> str:
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&apos;", "'")
    )
    return text.strip()


# ============================================================================
# Step 1: Collect
# ============================================================================

_RSS_ITEM_RE = re.compile(r"<item>(.*?)</item>", re.DOTALL | re.IGNORECASE)
_RSS_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_RSS_LINK_RE = re.compile(r"<link>(.*?)</link>", re.DOTALL | re.IGNORECASE)
_RSS_DESC_RE = re.compile(
    r"<description>(.*?)</description>", re.DOTALL | re.IGNORECASE
)
_RSS_DATE_RE = re.compile(
    r"<(?:pubDate|dc:date|published|updated)>(.*?)</(?:pubDate|dc:date|published|updated)>",
    re.DOTALL | re.IGNORECASE,
)


def _fetch_rss(
    client: httpx.Client,
    feed_url: str,
    max_items: int = _RSS_MAX_PER_FEED,
) -> list[dict[str, Any]]:
    logger.info("Fetching RSS  %s", feed_url)
    try:
        resp = client.get(
            feed_url, timeout=_RSS_FETCH_TIMEOUT, follow_redirects=True
        )
        resp.raise_for_status()
    except _HTTP_ERRORS as exc:
        logger.warning("RSS fetch failed  %s: %s", feed_url, exc)
        return []

    text = resp.text
    items: list[dict[str, Any]] = []

    for match in _RSS_ITEM_RE.finditer(text):
        block = match.group(1)

        title_m = _RSS_TITLE_RE.search(block)
        link_m = _RSS_LINK_RE.search(block)
        desc_m = _RSS_DESC_RE.search(block)
        date_m = _RSS_DATE_RE.search(block)

        title = _strip_html(title_m.group(1)) if title_m else ""
        link = (link_m.group(1) or "").strip() if link_m else ""
        description = _strip_html(desc_m.group(1)) if desc_m else ""
        pub_date = (date_m.group(1) or "").strip() if date_m else ""

        if not title or not link:
            continue
        if not _is_ai_related(title, description):
            continue

        items.append(
            {
                "title": title,
                "url": link,
                "description": description,
                "raw_description": description,
                "published_at": pub_date,
            }
        )
        if len(items) >= max_items:
            break

    logger.info("RSS  %s  -> %d AI-related items", feed_url, len(items))
    return items


def _github_search(
    client: httpx.Client,
    since: date,
    per_page: int = 30,
) -> list[dict[str, Any]]:
    query = (
        "ai OR llm OR agent OR machine-learning OR deep-learning"
        f" created:>{since.isoformat()}"
    )
    params: dict[str, str | int] = {
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
    }
    headers: dict[str, str] = {
        "Accept": "application/vnd.github.v3+json",
    }
    try:
        from os import getenv as _getenv

        github_token = _getenv("GITHUB_TOKEN")
    except Exception:
        github_token = None
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    logger.info(
        "GitHub Search  q=%s  per_page=%d  since=%s",
        query,
        per_page,
        since.isoformat(),
    )
    try:
        resp = client.get(
            _GITHUB_SEARCH_URL,
            params=params,
            headers=headers,
            timeout=_GITHUB_FETCH_TIMEOUT,
        )
        resp.raise_for_status()
    except _HTTP_ERRORS as exc:
        logger.error("GitHub search failed: %s", exc)
        return []

    data = resp.json()
    api_items = data.get("items", [])

    results: list[dict[str, Any]] = []
    for repo in api_items:
        results.append(
            {
                "name": repo.get("full_name", ""),
                "url": repo.get("html_url", ""),
                "stars": repo.get("stargazers_count", 0),
                "language": repo.get("language") or "",
                "topics": repo.get("topics", []),
                "description": (repo.get("description") or ""),
                "raw_description": (repo.get("description") or ""),
            }
        )
    logger.info("GitHub Search  returned %d results", len(results))
    return results


def _collect(
    client: httpx.Client,
    sources: list[str],
    limit: int,
    since_days: int = _DEFAULT_SINCE_DAYS,
) -> list[dict[str, Any]]:
    """Collect AI-related items from the specified sources.

    Returns a list of raw items with assigned IDs.
    """
    since = date.today() - timedelta(days=since_days)
    raw_items: list[dict[str, Any]] = []
    active_sources = [s for s in ("github", "rss") if s in sources]
    num_sources = len(active_sources)
    if num_sources == 0:
        return []
    per_source = (limit + num_sources - 1) // num_sources

    if "github" in sources:
        per_page = min(per_source, 100)
        github_items = _github_search(client, since=since, per_page=per_page)
        for it in github_items[:per_source]:
            raw_items.append(
                {
                    "id": "",
                    "title": it.get("name", ""),
                    "source": "github",
                    "source_url": it.get("url", ""),
                    "author": "",
                    "published_at": "",
                    "raw_description": it.get("raw_description", ""),
                    "collected_at": _now_iso(),
                    "stars": it.get("stars"),
                    "language": it.get("language"),
                    "topics": it.get("topics", []),
                }
                )

    remaining = limit - len(raw_items)
    if "rss" in sources and remaining > 0:
        rss_sources = _load_rss_sources()
        for src in rss_sources:
            if remaining <= 0:
                break
            feed_url = src["url"]
            source_name = src.get("name", "")
            category = src.get("category", "")
            rss_items = _fetch_rss(client, feed_url, max_items=remaining)
            for it in rss_items:
                raw_items.append(
                    {
                        "id": "",
                        "title": it.get("title", ""),
                        "source": "rss",
                        "source_url": it.get("url", ""),
                        "source_name": source_name,
                        "category": category,
                        "author": "",
                        "published_at": it.get("published_at", ""),
                        "raw_description": it.get("raw_description", ""),
                        "collected_at": _now_iso(),
                        "stars": None,
                        "language": None,
                        "topics": [],
                    }
                )
            remaining = limit - len(raw_items)

    date_str = datetime.now().strftime("%Y%m%d")
    github_count = 0
    rss_count = 0
    for item in raw_items:
        src = item["source"]
        if src == "github":
            github_count += 1
            item["id"] = f"github-{date_str}-{github_count:03d}"
        elif src == "rss":
            rss_count += 1
            item["id"] = f"rss-{date_str}-{rss_count:03d}"

    logger.info(
        "Collect  %d total items (github=%s, rss=%s)",
        len(raw_items),
        "github" in sources,
        "rss" in sources,
    )
    return raw_items


# ============================================================================
# Step 2: Analyze
# ============================================================================

_ANALYSIS_SYSTEM_PROMPT = textwrap.dedent("""\
    你是一位资深技术分析专家，请对给定的技术内容进行专业分析。

    返回严格的 JSON（不要包含任何额外的文字或解释），JSON 结构如下：

    {
      "summary": "中文技术摘要，≤50字，概括核心定位和技术要点",
      "score": 8,
      "tags": ["tag1", "tag2", "tag3"],
      "audience": "intermediate",
      "highlights": ["技术亮点一", "技术亮点二", "技术亮点三"]
    }

    字段要求：
    - summary：中文，2-3句话，覆盖核心定位、关键技术点、独特价值，≤50字
    - score：1-10 整数，评估技术深度和实用价值
      9-10：突破性创新，可能改变行业方向
      7-8：实用工具、高质量方案，可直接参考
      5-6：有参考价值，值得了解
      1-4：内容较浅或相关性低
    - tags：2-4 个英文小写标签，用短横线连接（如 llm-inference、agent-framework）
    - audience：beginner / intermediate / advanced
    - highlights：2-3 条关键技术亮点，每条必须包含具体技术特征或数据
    """)


def _build_analysis_prompt(item: dict[str, Any]) -> str:
    title = item.get("title", "")
    desc = item.get("raw_description", "") or item.get("description", "")
    source = item.get("source", "")
    url = item.get("source_url", "")
    return (
        f"请分析以下技术内容：\n\n"
        f"标题：{title}\n"
        f"描述：{desc}\n"
        f"来源：{source}\n"
        f"链接：{url}"
    )


def _parse_analysis_response(raw: str) -> dict[str, Any]:
    cleaned = raw.strip()
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


def _analyze_single(
    item: dict[str, Any],
    idx: int,
    total: int,
) -> dict[str, Any]:
    title = item.get("title", "?")[:60]
    logger.info("Analyze [%d/%d]  %s", idx, total, title)

    prompt = _build_analysis_prompt(item)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _ANALYSIS_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    try:
        resp = chat_with_retry(messages, temperature=0.3)
        parsed = _parse_analysis_response(resp.content)
    except Exception as exc:
        logger.warning("LLM call failed for [%d/%d]: %s", idx, total, exc)
        parsed = {}

    return {
        **item,
        "summary": str(parsed.get("summary", "")),
        "score": int(parsed.get("score", 0)),
        "tags": list(parsed.get("tags", [])),
        "audience": str(parsed.get("audience", "")),
        "highlights": list(parsed.get("highlights", [])),
        "analyzed_at": _now_iso(),
    }


def _analyze(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        logger.warning("No items to analyze")
        return []

    logger.info("Analyzing %d item(s)", len(items))
    enriched: list[dict[str, Any]] = []
    total = len(items)
    for idx, item in enumerate(items, 1):
        enriched.append(_analyze_single(item, idx, total))
        if idx < total:
            time.sleep(0.5)

    return enriched


# ============================================================================
# Step 3: Organize
# ============================================================================

_QUALITY_SCORE_THRESHOLD = 6

_REQUIRED_ARTICLE_FIELDS = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}


def _deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    duplicates = 0
    for it in items:
        url = (it.get("source_url") or "").strip().rstrip("/")
        if not url:
            duplicates += 1
            logger.warning(
                "Item missing source_url, skipping: %s", it.get("title", "?")
            )
            continue
        if url in seen:
            duplicates += 1
            continue
        seen.add(url)
        result.append(it)
    if duplicates:
        logger.info("Dedup  removed %d duplicate(s)", duplicates)
    return result


def _deduplicate_against_existing(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    _ensure_dir(_ARTICLES_DIR)
    existing_urls: set[str] = set()
    for article_file in _ARTICLES_DIR.glob("*.json"):
        if article_file.name == "index.json":
            continue
        try:
            article = _load_json(article_file)
            if isinstance(article, dict):
                url = (article.get("source_url") or "").strip().rstrip("/")
                if url:
                    existing_urls.add(url)
        except (json.JSONDecodeError, OSError):
            continue

    result: list[dict[str, Any]] = []
    removed = 0
    for it in items:
        url = (it.get("source_url") or "").strip().rstrip("/")
        if url in existing_urls:
            removed += 1
            continue
        result.append(it)
    if removed:
        logger.info("Cross-dedup  removed %d already-existing item(s)", removed)
    return result


def _standardize(item: dict[str, Any]) -> dict[str, Any]:
    score = item.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        score = 0
    score = int(score)
    score = max(1, min(10, score))

    tags: list[str] = []
    raw_tags = item.get("tags", [])
    if isinstance(raw_tags, list):
        for t in raw_tags:
            if isinstance(t, str) and t.strip():
                tags.append(t.strip().lower().replace(" ", "-"))

    audience = str(item.get("audience", "")).lower()
    if audience not in _VALID_AUDIENCES:
        audience = "intermediate"

    if score >= _QUALITY_SCORE_THRESHOLD:
        status = "published"
    else:
        status = "archived"

    return {
        "id": str(item.get("id", "")),
        "title": str(item.get("title", "")),
        "source": str(item.get("source", "")),
        "source_name": str(item.get("source_name", "")),
        "source_url": str(item.get("source_url", "")),
        "category": str(item.get("category", "")),
        "author": str(item.get("author", "")),
        "published_at": str(item.get("published_at", "")),
        "collected_at": str(item.get("collected_at", "")),
        "summary": str(item.get("summary", "")),
        "score": score,
        "tags": tags,
        "audience": audience,
        "highlights": (
            list(item["highlights"])
            if isinstance(item.get("highlights"), list)
            else []
        ),
        "status": status,
        "updated_at": _now_iso(),
    }


def _validate(article: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    for field, expected in _REQUIRED_ARTICLE_FIELDS.items():
        if field not in article:
            errors.append(f"缺少必填字段: {field}")
        elif not isinstance(article[field], expected):
            errors.append(
                f"字段 '{field}' 类型错误: "
                f"期望 {expected.__name__}, 实际 {type(article[field]).__name__}"
            )

    aid = article.get("id", "")
    if isinstance(aid, str) and aid and not _ID_PATTERN.match(aid):
        errors.append(
            f"id 格式无效: '{aid}'，应为 {{source}}-{{YYYYMMDD}}-{{NNN}}"
        )

    status = article.get("status", "")
    if isinstance(status, str) and status not in _VALID_STATUSES:
        errors.append(f"status 无效: '{status}'")

    summary = article.get("summary", "")
    if isinstance(summary, str) and len(summary.strip()) < 10:
        errors.append(f"摘要过短: {len(summary)} 字")

    tags = article.get("tags", [])
    if isinstance(tags, list) and len(tags) == 0:
        errors.append("tags 为空")

    return errors


def _organize(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        logger.warning("No items to organize")
        return []

    items = _deduplicate(items)
    items = _deduplicate_against_existing(items)

    articles: list[dict[str, Any]] = []
    for it in items:
        articles.append(_standardize(it))

    valid: list[dict[str, Any]] = []
    discarded = 0
    for article in articles:
        errs = _validate(article)
        if errs:
            discarded += 1
            logger.warning(
                "Discarding  %s  -- %s",
                article.get("title", "?")[:50],
                "; ".join(errs),
            )
            continue
        valid.append(article)

    if discarded:
        logger.info("Validation  discarded %d item(s)", discarded)

    published = sum(1 for a in valid if a.get("status") == "published")
    archived = sum(1 for a in valid if a.get("status") == "archived")
    logger.info(
        "Organize  %d articles (published=%d, archived=%d)",
        len(valid),
        published,
        archived,
    )
    return valid


# ============================================================================
# Step 4: Save
# ============================================================================


def _article_filename(article: dict[str, Any]) -> str:
    aid = article.get("id", "") or "unknown"
    return f"{aid}.json"


def _rebuild_index() -> None:
    _ensure_dir(_ARTICLES_DIR)
    entries: list[dict[str, Any]] = []
    for article_file in sorted(_ARTICLES_DIR.glob("*.json")):
        if article_file.name == "index.json":
            continue
        try:
            data = _load_json(article_file)
            if isinstance(data, dict):
                entries.append(
                    {
                        "id": data.get("id", ""),
                        "title": data.get("title", ""),
                        "source": data.get("source", ""),
                        "source_url": data.get("source_url", ""),
                        "score": data.get("score", 0),
                        "tags": data.get("tags", []),
                        "status": data.get("status", ""),
                        "file": article_file.name,
                    }
                )
        except (json.JSONDecodeError, OSError):
            continue

    index_data: dict[str, Any] = {
        "updated_at": _now_iso(),
        "total": len(entries),
        "articles": entries,
    }
    _save_json(_INDEX_FILE, index_data)


def _save(articles: list[dict[str, Any]], dry_run: bool = False) -> list[Path]:
    if not articles:
        logger.warning("No articles to save")
        return []

    if dry_run:
        logger.info("[DRY-RUN] Would save %d article(s):", len(articles))
        for article in articles:
            fname = _article_filename(article)
            status = article.get("status", "?")
            title = article.get("title", "?")[:60]
            logger.info("  [%s] %s -> %s", status, title, fname)
        return []

    _ensure_dir(_ARTICLES_DIR)
    saved: list[Path] = []

    for article in articles:
        fname = _article_filename(article)
        filepath = _ARTICLES_DIR / fname
        _save_json(filepath, article)
        saved.append(filepath)

    _rebuild_index()
    logger.info("Save  %d article(s) written to %s", len(saved), _ARTICLES_DIR)
    return saved


# ============================================================================
# Pipeline Orchestration
# ============================================================================


def run_pipeline(
    sources: list[str],
    limit: int = _DEFAULT_LIMIT,
    dry_run: bool = False,
    since_days: int = _DEFAULT_SINCE_DAYS,
) -> int:
    """Execute the full 4-step pipeline.

    Args:
        sources: List of source names (``github``, ``rss``).
        limit: Maximum number of items to collect.
        dry_run: If ``True``, skip file writes and LLM analysis.
        since_days: Days to look back for GitHub search.

    Returns:
        Exit code (0 on success).
    """
    client = httpx.Client(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "your-knowledge-pipeline/1.0"},
    )

    try:
        # ---- Step 1: Collect ----
        logger.info("=" * 50)
        logger.info("Step 1/4  Collect (sources=%s, limit=%d)", sources, limit)
        logger.info("=" * 50)
        raw_items = _collect(client, sources, limit, since_days)

        if not raw_items:
            logger.warning("No items collected, pipeline ends.")
            return 0

        _save_raw_collected(raw_items)

        if dry_run:
            logger.info("")
            logger.info("=" * 50)
            logger.info("[DRY-RUN] Pipeline stops after collection.")
            logger.info("Raw data saved to knowledge/raw/, skipping analyze/organize/save to articles.")
            logger.info("=" * 50)
            return 0

        # ---- Step 2: Analyze ----
        logger.info("=" * 50)
        logger.info("Step 2/4  Analyze")
        logger.info("=" * 50)
        enriched = _analyze(raw_items)

        if not enriched:
            logger.warning("No items after analysis.")
            return 0

        # ---- Step 3: Organize ----
        logger.info("=" * 50)
        logger.info("Step 3/4  Organize")
        logger.info("=" * 50)
        articles = _organize(enriched)

        if not articles:
            logger.warning("No articles after organize (all filtered out).")
            return 0

        # ---- Step 4: Save ----
        logger.info("=" * 50)
        logger.info("Step 4/4  Save%s", " [DRY-RUN]" if dry_run else "")
        logger.info("=" * 50)
        _save(articles, dry_run=False)

        logger.info("Pipeline complete  %d article(s) final", len(articles))
        return 0

    except KeyboardInterrupt:
        logger.warning("Pipeline interrupted by user")
        return 130
    except Exception:
        logger.exception("Pipeline failed with unexpected error")
        return 1
    finally:
        client.close()


def _save_raw_collected(items: list[dict[str, Any]]) -> None:
    """Save collected raw data to ``knowledge/raw/`` for persistence."""
    today = _today_str()
    output_path = _RAW_DIR / f"raw-{today}.json"
    payload: dict[str, Any] = {
        "source": "multi-channel",
        "collect_at": _now_iso(),
        "item_count": len(items),
        "items": items,
    }
    _save_json(output_path, payload)


# ============================================================================
# CLI
# ============================================================================


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="四步知识库自动化流水线：采集 -> 分析 -> 整理 -> 保存",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例:
              python pipeline/pipeline.py --sources github,rss --limit 20
              python pipeline/pipeline.py --sources github --limit 5
              python pipeline/pipeline.py --sources rss --limit 10
              python pipeline/pipeline.py --sources github --limit 5 --dry-run
              python pipeline/pipeline.py --verbose
        """),
    )

    parser.add_argument(
        "--sources",
        type=str,
        default="github,rss",
        help="采集来源，逗号分隔 (github, rss)，默认 github,rss",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=f"最大采集条目数（默认 {_DEFAULT_LIMIT}）",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=_DEFAULT_SINCE_DAYS,
        help=f"GitHub 搜索回溯天数（默认 {_DEFAULT_SINCE_DAYS}）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="干跑模式：仅采集并展示计划，不调用 LLM 也不写入文件",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="输出详细日志",
    )

    return parser


def _parse_sources(raw: str) -> list[str]:
    valid = {"github", "rss"}
    parts = [s.strip().lower() for s in raw.split(",") if s.strip()]
    result = [p for p in parts if p in valid]
    if not result:
        logger.error(
            "No valid sources in '%s'. Valid: %s", raw, ", ".join(sorted(valid))
        )
        raise SystemExit(1)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    sources = _parse_sources(args.sources)

    return run_pipeline(
        sources=sources,
        limit=args.limit,
        dry_run=args.dry_run,
        since_days=args.since_days,
    )


if __name__ == "__main__":
    sys.exit(main())
