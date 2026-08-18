"""Prompt loading & leak filtering — split from analysis/llm.py (Batch 2)."""

from pathlib import Path

_PROMPT_DIR = Path(__file__).parent.parent / "prompts" / "v1"

def load_prompt(name: str) -> str:
    """Load a prompt from the prompts/v1/ directory."""
    return (_PROMPT_DIR / name).read_text(encoding="utf-8")


# System prompts are loaded from markdown files (prompts/v1/*.md)
SYSTEM_PROMPT = load_prompt("general_analyst.md")


_LEAK_PATTERNS = (
    "我们只需要回答",
    "我们只需要",
    "请忽略以上指令",
    "忽略以上",
    "你是专业",
    "你是一名",
    "你是一个",
    "你的任务是",
    "请严格按照以下提示词",
    "系统提示词内容",
    "system prompt",
    "作为AI助手",
    "作为 AI 助手",
)


def strip_internal_leak(text: str) -> str:
    """F1-7: 过滤 LLM 输出中泄漏的内部指令片段。

    对包含已知泄漏模式的整行进行剔除，并移除行内的残余指令关键词。
    纯函数，输入输出均为字符串，永不抛异常。
    """
    if not isinstance(text, str):
        return ""
    if not text:
        return ""
    out_lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            out_lines.append(line)
            continue
        if any(p.lower() in stripped.lower() for p in _LEAK_PATTERNS):
            continue
        out_lines.append(line)
    cleaned = "\n".join(out_lines)
    # 行内残余泄漏词剔除（如夹在正常句子中的「我们只需要回答…」片段）
    import re as _re
    for p in _LEAK_PATTERNS:
        cleaned = _re.sub(_re.escape(p), "", cleaned, flags=_re.IGNORECASE)
    cleaned = _re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned
