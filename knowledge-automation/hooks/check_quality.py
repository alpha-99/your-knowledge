#!/usr/bin/env python3
"""Check quality of knowledge article JSON files across 5 dimensions.

Usage:
    python hooks/check_quality.py <json_file> [json_file2 ...]
    python hooks/check_quality.py knowledge/articles/*.json
"""

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# =====================================================================
# Constants
# =====================================================================

VALID_STATUSES = {"draft", "review", "published", "archived"}

_CHINESE_BUZZWORDS = [
    "赋能", "抓手", "闭环", "打通", "全链路", "底层逻辑",
    "颗粒度", "对齐", "拉通", "沉淀", "强大的", "革命性的",
]

_ENGLISH_BUZZWORDS = [
    "groundbreaking", "revolutionary", "game-changing", "cutting-edge",
    "disruptive", "best-in-class", "world-class",
    "next-generation", "paradigm-shifting", "unprecedented",
    "state-of-the-art", "bleeding-edge",
]

_BUZZWORD_CN = re.compile("|".join(re.escape(w) for w in _CHINESE_BUZZWORDS))
_BUZZWORD_EN = re.compile(
    "|".join(re.escape(w) for w in _ENGLISH_BUZZWORDS), re.IGNORECASE
)

_TECH_KEYWORDS = re.compile(
    r"(?i)\b("
    r"llm|agent|rag|fine[-\s]?tun|transformer|embedding|vector|"
    r"prompt|inference|token|model|diffusion|langchain|langgraph|"
    r"openai|anthropic|claude|gemini|llama|mixtral|deepseek|qwen|"
    r"mcp|protocol|api|framework|pipeline|training|benchmark|"
    r"neural|dataset|open[-\s]?source|github|arxiv|architecture|"
    r"orchestrat|retrieval|augmented|generation|reasoning|"
    r"multi[-\s]?modal|context[-\s]?window|quantization|"
    r"curation|grpo|rlhf|dpo|sft|supervised|pre[-\s]?train|"
    r"attention|cache|latency|throughput|serving|cuda|tensor"
    r")\b"
)

_STANDARD_TAGS = {
    "agent", "agent-framework", "agent-orchestration", "multi-agent",
    "llm", "large-language-model", "llm-inference", "llm-training",
    "llm-evaluation", "llm-fine-tuning", "llm-deployment",
    "rag", "retrieval-augmented-generation",
    "prompt", "prompt-engineering",
    "mcp", "mcp-protocol", "mcp-server", "mcp-client",
    "langchain", "langgraph", "llamaindex", "crewai",
    "openai", "gpt", "claude", "gemini", "llama", "mixtral",
    "deepseek", "qwen", "mistral", "anthropic",
    "tool-use", "tool-calling", "function-calling",
    "vector-database", "embedding", "knowledge-base", "knowledge-graph",
    "transformer", "attention-mechanism", "diffusion-model",
    "neural-network", "deep-learning", "machine-learning",
    "local-inference", "edge-computing", "model-deployment",
    "quantization", "gguf", "ollama", "vllm", "tgi",
    "dataset", "fine-tuning", "rlhf", "dpo", "sft",
    "benchmark", "evaluation", "safety", "alignment",
    "code-generation", "code-assistant", "chatbot", "copilot",
    "open-source", "open-source-model",
    "python", "javascript", "typescript", "rust", "go",
    "api", "sdk", "library", "framework", "cli",
    "paper", "research", "survey", "tutorial",
    "text-generation", "image-generation",
    "docker", "kubernetes", "cloud",
}

# =====================================================================
# Data Classes
# =====================================================================


@dataclass
class DimensionScore:
    """Score for a single quality dimension."""
    name: str
    score: float
    max_score: float
    details: str = ""


@dataclass
class QualityReport:
    """Full quality report for a knowledge article."""
    filepath: Path
    dimensions: list[DimensionScore] = field(default_factory=list)
    total_score: float = 0.0
    max_total: float = 100.0
    grade: str = "C"
    errors: list[str] = field(default_factory=list)


# =====================================================================
# Dimension Scorers
# =====================================================================


def _score_summary_quality(data: dict) -> DimensionScore:
    """Score summary quality (max 25).

    Length tiers:
      >= 50 chars : base 20 (满分)
      >= 20 chars : base 15 (基本分)
       < 20 chars : proportional

    Tech keyword bonus: up to +5.
    """
    dim = DimensionScore(name="摘要质量", score=0.0, max_score=25.0)
    summary = data.get("summary", "")
    if not isinstance(summary, str):
        dim.details = "摘要字段缺失或类型错误"
        return dim

    length = len(summary)
    if length >= 50:
        base = 20.0
        tier = "满分"
    elif length >= 20:
        base = 15.0
        tier = "基本"
    else:
        base = (length / 20.0) * 15.0
        tier = "不足"

    keywords = set(_TECH_KEYWORDS.findall(summary))
    kw_count = len(keywords)
    if kw_count >= 5:
        bonus = 5.0
    elif kw_count >= 3:
        bonus = 3.0
    elif kw_count >= 1:
        bonus = 2.0
    else:
        bonus = 0.0

    dim.score = round(min(base + bonus, 25.0), 1)
    dim.details = f"长度={length}字({tier}), 技术关键词={kw_count}个"
    return dim


def _score_technical_depth(data: dict) -> DimensionScore:
    """Score technical depth from article score field (max 25).

    Linearly maps score 1–10 to 0–25.
    """
    dim = DimensionScore(name="技术深度", score=0.0, max_score=25.0)
    score_val = data.get("score")

    if score_val is None:
        dim.details = "缺少 score 字段"
        return dim
    if not isinstance(score_val, (int, float)) or isinstance(score_val, bool):
        dim.details = f"score 类型错误: {type(score_val).__name__}"
        return dim
    if score_val < 1 or score_val > 10:
        dim.details = f"score 超出范围: {score_val}"
        return dim

    dim.score = round(score_val * 2.5, 1)
    dim.details = f"文章评分={score_val}/10 → {dim.score}/25"
    return dim


def _score_format_compliance(data: dict) -> DimensionScore:
    """Score format compliance (max 20).

    5 items × 4 points each:
      id, title, source_url, status, timestamp
    """
    dim = DimensionScore(name="格式规范", score=0.0, max_score=20.0)
    passed = 0
    marks: list[str] = []

    # id — present and non-empty
    if isinstance(data.get("id"), str) and data["id"].strip():
        passed += 1
        marks.append("id ✓")
    else:
        marks.append("id ✗")

    # title
    if isinstance(data.get("title"), str) and data["title"].strip():
        passed += 1
        marks.append("title ✓")
    else:
        marks.append("title ✗")

    # source_url
    if isinstance(data.get("source_url"), str) and data["source_url"].strip():
        passed += 1
        marks.append("url ✓")
    else:
        marks.append("url ✗")

    # status — must be one of the valid values
    status = data.get("status")
    if isinstance(status, str) and status in VALID_STATUSES:
        passed += 1
        marks.append("status ✓")
    else:
        marks.append("status ✗")

    # timestamp — at least one of collected_at / published_at / updated_at
    ts_keys = ("collected_at", "published_at", "updated_at")
    has_ts = any(
        isinstance(data.get(k), str) and data[k].strip() for k in ts_keys
    )
    if has_ts:
        passed += 1
        marks.append("ts ✓")
    else:
        marks.append("ts ✗")

    dim.score = passed * 4.0
    dim.details = "  ".join(marks)
    return dim


def _score_tag_precision(data: dict) -> DimensionScore:
    """Score tag precision (max 15).

    - Count bonus: 1–3 tags is ideal (10); 4→7; 5→5; 6+→gradual.
    - Quality bonus: ratio of standard tags × 5.
    """
    dim = DimensionScore(name="标签精度", score=0.0, max_score=15.0)
    tags = data.get("tags", [])

    if not isinstance(tags, list):
        dim.details = "tags 不是列表"
        return dim

    valid = [t for t in tags if isinstance(t, str) and t.strip()]
    if not valid:
        dim.details = "无有效标签"
        return dim

    count = len(valid)
    if 1 <= count <= 3:
        base = 10.0
    elif count == 4:
        base = 7.0
    elif count == 5:
        base = 5.0
    else:
        base = max(3.0, 10.0 - (count - 3))

    std_count = sum(1 for t in valid if t.lower() in _STANDARD_TAGS)
    quality_ratio = std_count / count if count > 0 else 0.0
    quality_bonus = quality_ratio * 5.0

    dim.score = round(min(base + quality_bonus, 15.0), 1)
    dim.details = f"标签数={count}, 标准标签={std_count}/{count}"
    return dim


def _score_buzzword_detection(data: dict) -> DimensionScore:
    """Score buzzword detection (max 15).

    Checks summary, title, highlights for hollow words.
    Start at 15, −3 per unique buzzword found.
    """
    dim = DimensionScore(name="空洞词检测", score=15.0, max_score=15.0)

    texts: list[str] = []
    for field in ("summary", "title", "highlights"):
        val = data.get(field)
        if isinstance(val, str):
            texts.append(val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    texts.append(item)

    blob = "\n".join(texts)

    cn_hits = set(_BUZZWORD_CN.findall(blob))
    en_hits = set(_BUZZWORD_EN.findall(blob))

    deduction = (len(cn_hits) + len(en_hits)) * 3.0
    dim.score = round(max(15.0 - deduction, 0.0), 1)

    all_hits = sorted(cn_hits | en_hits)
    dim.details = (
        f"命中: {', '.join(all_hits)}" if all_hits else "未检测到空洞词"
    )
    return dim


# =====================================================================
# Assessment Pipeline
# =====================================================================

_DIMENSION_SCORERS = [
    _score_summary_quality,
    _score_technical_depth,
    _score_format_compliance,
    _score_tag_precision,
    _score_buzzword_detection,
]


def assess_article(filepath: Path) -> QualityReport:
    """Run all 5 dimension scorers against a single article JSON."""
    report = QualityReport(filepath=filepath)

    try:
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        report.errors.append(f"JSON 解析失败: {e}")
        return report
    except OSError as e:
        report.errors.append(f"文件读取失败: {e}")
        return report

    if not isinstance(data, dict):
        report.errors.append("顶层不是 JSON 对象")
        return report

    for scorer in _DIMENSION_SCORERS:
        report.dimensions.append(scorer(data))

    report.total_score = sum(d.score for d in report.dimensions)

    if report.total_score >= 80:
        report.grade = "A"
    elif report.total_score >= 60:
        report.grade = "B"
    else:
        report.grade = "C"

    return report


# =====================================================================
# Output Helpers
# =====================================================================

_GRADE_COLORS = {"A": "\033[92m", "B": "\033[93m", "C": "\033[91m"}
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"


def _progress_bar(current: int, total: int, width: int = 30) -> str:
    """Render a text-based progress bar."""
    if total == 0:
        return "[                              ] 0/0"
    filled = int(width * current / total)
    bar = "█" * filled + "░" * (width - filled)
    pct = int(current / total * 100)
    return f"[{bar}] {current}/{total} ({pct}%)"


def print_report(report: QualityReport) -> None:
    """Pretty-print a single quality report."""
    name = report.filepath.name

    print(f"\n{_BOLD}── {name} ──{_RESET}")

    if report.errors:
        for err in report.errors:
            print(f"  ❌ {err}")
        print(f"  {_GRADE_COLORS['C']}等级: {report.grade} (错误){_RESET}")
        return

    for dim in report.dimensions:
        ratio = dim.score / dim.max_score if dim.max_score else 0
        bar_len = int(ratio * 20)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        print(
            f"  {dim.name:　<5} [{bar}] "
            f"{dim.score:.1f}/{dim.max_score:.0f}  {dim.details}"
        )

    color = _GRADE_COLORS.get(report.grade, "")
    print(
        f"  {'总计':　<5} {color}{_BOLD}{report.total_score:.1f}/100  "
        f"等级: {report.grade}{_RESET}"
    )


# =====================================================================
# Path Utilities
# =====================================================================


def _has_glob_chars(pat: str) -> bool:
    return bool(set("*?[]") & set(pat))


def expand_paths(patterns: list[str]) -> list[Path]:
    """Expand glob patterns into a deduplicated, sorted list of Paths."""
    files: list[Path] = []
    for pat in patterns:
        p = Path(pat)
        if p.is_file():
            files.append(p)
            continue

        if p.is_absolute():
            matches = (
                sorted(p.parent.glob(p.name)) if _has_glob_chars(pat) else []
            )
        else:
            if _has_glob_chars(pat):
                matches = sorted(Path().glob(pat))
            elif p.exists():
                matches = [p]
            else:
                matches = []

        if not matches:
            print(f"警告: 未找到匹配文件: {pat}", file=sys.stderr)
        files.extend(matches)

    seen: set[str] = set()
    result: list[Path] = []
    for f in sorted(files):
        key = str(f.resolve())
        if key not in seen:
            seen.add(key)
            result.append(f)
    return result


# =====================================================================
# Main
# =====================================================================


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "用法: python hooks/check_quality.py <json_file> [json_file2 ...]",
            file=sys.stderr,
        )
        print(
            "支持通配符，如: python hooks/check_quality.py knowledge/articles/*.json",
            file=sys.stderr,
        )
        return 1

    all_files = expand_paths(sys.argv[1:])
    json_files = [
        f for f in all_files if f.suffix == ".json" and f.name != "index.json"
    ]

    if not json_files:
        print("未找到匹配的 JSON 文件", file=sys.stderr)
        return 1

    reports: list[QualityReport] = []
    total = len(json_files)

    for idx, fp in enumerate(json_files, 1):
        report = assess_article(fp)
        reports.append(report)
        print_report(report)
        print(f"  {_DIM}{_progress_bar(idx, total)}{_RESET}")

    # Summary
    print()
    grade_counts: dict[str, int] = {"A": 0, "B": 0, "C": 0}
    for r in reports:
        grade_counts[r.grade] += 1

    print(f"{_BOLD}质量检查完成: 共 {total} 个文件{_RESET}")
    print(f"  {_GRADE_COLORS['A']}A 级: {grade_counts['A']}{_RESET}")
    print(f"  {_GRADE_COLORS['B']}B 级: {grade_counts['B']}{_RESET}")
    print(f"  {_GRADE_COLORS['C']}C 级: {grade_counts['C']}{_RESET}")

    return 1 if grade_counts["C"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
