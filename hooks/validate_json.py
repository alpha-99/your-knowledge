#!/usr/bin/env python3
"""Validate knowledge article JSON files.

Usage:
    python hooks/validate_json.py <json_file> [json_file2 ...]
    python hooks/validate_json.py knowledge/articles/*.json
"""

import json
import re
import sys
from pathlib import Path

REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}

VALID_STATUSES = {"draft", "review", "published", "archived"}
VALID_AUDIENCES = {"beginner", "intermediate", "advanced"}

ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*-\d{8}-\d{3}$")
URL_PATTERN = re.compile(r"^https?://")


def _has_glob_chars(pat: str) -> bool:
    """Check if pattern contains wildcard characters."""
    return bool(set("*?[]") & set(pat))


def expand_paths(patterns: list[str]) -> list[Path]:
    """Expand patterns into a deduplicated, sorted list of Path objects."""
    files: list[Path] = []
    for pat in patterns:
        p = Path(pat)
        if p.is_file():
            files.append(p)
            continue

        if p.is_absolute():
            if _has_glob_chars(pat):
                matches = sorted(p.parent.glob(p.name))
            else:
                matches = []
            if not matches:
                print(f"警告: 未找到匹配文件: {pat}", file=sys.stderr)
            files.extend(matches)
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


def validate_file(filepath: Path) -> list[str]:
    """Validate a single JSON file. Returns list of error messages."""
    errors: list[str] = []
    label = str(filepath)

    try:
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return [f"[{label}] JSON 解析失败: {e}"]
    except OSError as e:
        return [f"[{label}] 文件读取失败: {e}"]

    if not isinstance(data, dict):
        return [f"[{label}] 不是有效的知识条目（顶层应为 JSON 对象，而非 {type(data).__name__}）"]

    has_missing = False
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in data:
            errors.append(f"[{label}] 缺少必填字段: {field}")
            has_missing = True
        elif not isinstance(data[field], expected_type):
            actual = type(data[field]).__name__
            errors.append(
                f"[{label}] 字段 '{field}' 类型错误: "
                f"期望 {expected_type.__name__}, 实际 {actual}"
            )

    if has_missing:
        return errors

    # --- ID 格式 ---
    if isinstance(data["id"], str) and not ID_PATTERN.match(data["id"]):
        errors.append(
            f"[{label}] ID 格式错误: '{data['id']}'，"
            f"应为 {{source}}-{{YYYYMMDD}}-{{NNN}}（如 github-20260513-001）"
        )

    # --- status ---
    if isinstance(data["status"], str) and data["status"] not in VALID_STATUSES:
        errors.append(
            f"[{label}] status 值无效: '{data['status']}'，"
            f"合法值: {', '.join(sorted(VALID_STATUSES))}"
        )

    # --- URL ---
    if isinstance(data["source_url"], str) and not URL_PATTERN.match(data["source_url"]):
        errors.append(f"[{label}] source_url 格式错误: '{data['source_url']}'")

    # --- summary 长度 ---
    if isinstance(data["summary"], str):
        summary_len = len(data["summary"].strip())
        if summary_len < 20:
            errors.append(
                f"[{label}] 摘要过短: {summary_len} 字（最少需要 20 字）"
            )

    # --- tags ---
    if isinstance(data["tags"], list):
        if len(data["tags"]) == 0:
            errors.append(f"[{label}] tags 为空，至少需要 1 个标签")
        else:
            for i, t in enumerate(data["tags"]):
                if not isinstance(t, str) or not t.strip():
                    errors.append(f"[{label}] tags[{i}] 无效: 应为非空字符串")

    # --- score（可选） ---
    if "score" in data:
        score = data["score"]
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            errors.append(
                f"[{label}] score 类型错误: "
                f"期望 int/float, 实际 {type(score).__name__}"
            )
        elif not (1 <= score <= 10):
            errors.append(f"[{label}] score 超出范围: {score}，应在 1-10 之间")

    # --- audience（可选） ---
    if "audience" in data:
        if data["audience"] not in VALID_AUDIENCES:
            errors.append(
                f"[{label}] audience 值无效: '{data['audience']}'，"
                f"合法值: {', '.join(sorted(VALID_AUDIENCES))}"
            )

    return errors


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python hooks/validate_json.py <json_file> [json_file2 ...]")
        print("支持通配符，如: python hooks/validate_json.py knowledge/articles/*.json")
        return 1

    files = expand_paths(sys.argv[1:])

    total = 0
    passed = 0
    failed = 0

    for fp in files:
        if fp.suffix != ".json":
            continue
        if fp.name == "index.json":
            continue

        total += 1
        errors = validate_file(fp)
        if errors:
            failed += 1
            for err in errors:
                print(err)
        else:
            passed += 1

    print()
    print(f"校验完成: 共 {total} 个文件, 通过 {passed} 个, 失败 {failed} 个")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
