"""
news_level_audit.py -- 真实新闻采样质量门禁

对运行中的后端 /news/headlines 做一次采样，
检查每条新闻的 level/stars 是否符合内容直觉，
标记可能误判的条目并输出 WARNING。

不阻断 CI（exit code 0），适合 commit 前手动跑或集成到 verify_e2e --module news 做扩展。

用法:
  python scripts/news_level_audit.py                     # 默认检查 headlines
  python scripts/news_level_audit.py --endpoint macro    # 检查宏观新闻
  python scripts/news_level_audit.py --endpoint global   # 检查全球新闻
  python scripts/news_level_audit.py --verbose           # 显示全部条目
"""
import json
import sys

import requests

BASE = "http://127.0.0.1:8000"
TIMEOUT = 35
PASS = 0
WARN = 0


def check(label, ok, detail=""):
    global PASS, WARN
    if ok:
        PASS += 1
        mark = "PASS"
    else:
        WARN += 1
        mark = "WARN"
    print(f"  [{mark}] {label}" + (f" -- {detail}" if detail else ""))


# 词 -> 建议最低级别（标题含此词不应低于该级）
_MIN_LEVEL = {
    "台风": 5, "地震": 5, "恐怖袭击": 5, "airstrike": 5, "collapse": 5,
    "利好": 4, "降息": 4, "降准": 4, "增持": 4, "回购": 4,
    "利空": 3, "暴跌": 3, "做空": 3, "减持": 3, "亏损": 3,
    "sanctions": 3, "layoffs": 3,
}

# 词 -> 建议最高级别（标题含此词不应高于该级）
_MAX_LEVEL = {
    "提醒": 3, "关注": 3, "预告": 3, "展望": 3,
    "重磅": 3,
}


def audit_item(item: dict, verbose: bool) -> list[str]:
    """检查一条新闻的 level 合理性，返回问题列表。"""
    title = item.get("title", "")
    level = item.get("level", 0)
    stars = item.get("stars", 0)
    source = item.get("source", "")
    t = (title or "").lower()
    problems = []

    # 1. 最小值检查
    for word, min_lvl in _MIN_LEVEL.items():
        if word in t and level < min_lvl:
            problems.append(
                f'"{word}" 出现但 L={level} < 建议 {min_lvl}'
            )

    # 2. 最大值检查
    for word, max_lvl in _MAX_LEVEL.items():
        if word in t and level > max_lvl:
            problems.append(
                f'"{word}" 出现但 L={level} > 建议 {max_lvl}'
            )

    # 3. L1 但含高级别关键词
    if level == 1:
        for word in list(_MIN_LEVEL.keys()):
            if word in t:
                problems.append(f'L1 但含高级别词 "{word}"')
                break

    # 4. stars 不应低于 level
    if stars < level:
        problems.append(f"stars({stars}) < level({level}) -- 预期 >= level")

    # 5. level 范围
    if not (1 <= level <= 5):
        problems.append(f"level={level} 超出 1-5 范围")

    if verbose or problems:
        lvl_str = f"L{level}S{stars}"
        print(f"  {lvl_str:<8} [{source:<10}] {title[:80]}")

    return problems


def audit(endpoint: str, verbose: bool):
    """采样一个新闻端点。"""
    url = f"{BASE}/api/v1/news/{endpoint}"
    label = f"/news/{endpoint}"
    print(f"\n--- {label} ---")

    try:
        r = requests.get(url, timeout=TIMEOUT)
        check(f"GET {label} -> {r.status_code}", r.status_code == 200)
        if r.status_code != 200:
            return

        data = r.json()
        if not isinstance(data, list):
            check("返回格式为 list", False, f"实际为 {type(data).__name__}")
            return

        check(f"返回 {len(data)} 条", len(data) > 0)
        print()

        all_problems = []
        for item in data:
            problems = audit_item(item, verbose)
            if problems:
                all_problems.append((item.get("title", "")[:60], problems))
                for p in problems:
                    print(f"         ! {p}")

        if not all_problems:
            print("  OK: 未发现明显误判")
        else:
            print(f"\n  ! 共 {len(all_problems)} 条新闻存在潜在误判")

    except requests.Timeout:
        check(f"GET {label}", False, "请求超时")
    except requests.ConnectionError:
        check(f"GET {label}", False, f"无法连接 {BASE}，后端是否在运行？")
    except Exception as e:
        check(f"GET {label}", False, str(e))


def main():
    import argparse
    parser = argparse.ArgumentParser(description="新闻等级质量审计")
    parser.add_argument("--endpoint", default="headlines",
                        choices=["headlines", "macro", "global"])
    parser.add_argument("--verbose", action="store_true",
                        help="显示全部条目")
    args = parser.parse_args()

    print("=" * 60)
    print("  News Level Audit")
    print("=" * 60)

    audit(args.endpoint, args.verbose)

    total = PASS + WARN
    print(f"\n{'='*60}")
    print(f"  结果: {PASS} passed, {WARN} warnings (共 {total} 项检查)")
    print(f"  exit code 0 (信息性检查，不阻断 CI)")
    print(f"{'='*60}")
    sys.exit(0)


if __name__ == "__main__":
    main()
