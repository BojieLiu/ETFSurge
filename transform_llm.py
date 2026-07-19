#!/usr/bin/env python3
"""Transform llm.py: replace llm_complete_stream and llm_complete_with_system bodies."""
import ast
import sys

FILE = r"E:\ETF_Surge\backend\app\analysis\llm.py"

with open(FILE, "r", encoding="utf-8") as f:
    source = f.read()
    lines = source.splitlines(keepends=True)

# ---- Find function boundaries via AST ----
tree = ast.parse(source)

# Get the line ranges for the two functions to replace
# We need to find both functions and their exact line ranges
func_ranges = {}
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        name = node.name
        # AST lines are 1-based; end_lineno is inclusive
        start = node.lineno - 1  # convert to 0-based
        end = node.end_lineno    # end_lineno is 1-based inclusive
        func_ranges[name] = (start, end)

print("Functions found:", list(func_ranges.keys()), file=sys.stderr)
for name, (s, e) in sorted(func_ranges.items(), key=lambda x: x[1][0]):
    print(f"  {name}: lines {s+1}-{e}", file=sys.stderr)

# ---- Replacement 1: llm_complete_stream ----
if "llm_complete_stream" not in func_ranges:
    print("ERROR: llm_complete_stream not found in AST", file=sys.stderr)
    sys.exit(1)

s_start, s_end = func_ranges["llm_complete_stream"]

new_stream = '''async def llm_complete_stream(
    system_prompt: str,
    prompt: str,
    response_format: dict | None = None,
    temperature: float = 0.3,
    max_tokens: int = 8192,
) -> AsyncGenerator[dict, None]:
    """
    Streaming LLM completion with provider failover.
    
    Tries providers in priority order. If the primary provider fails
    BEFORE any token is yielded, falls back to the next provider.
    Once a token has been yielded, commits to that provider.
    
    Yields:
        {"type": "token", "token": "..."} - incremental token
        {"type": "done", "full_text": "...", "usage": {...}} - completion with full text
        {"type": "error", "error": "..."} - error occurred
    """
    import httpx
    await _check_key()

    providers = get_configured_providers()
    last_exc: Exception | None = None

    for provider in providers:
        body = {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens or 8192,
            "stream": True,
        }
        if response_format:
            body["response_format"] = response_format

        _start = time.monotonic()
        _caller = sys._getframe(1).f_code.co_name

        full_text = ""
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        try:
            async with httpx.AsyncClient(
                timeout=provider.timeout, trust_env=False
            ) as client:
                async with client.stream(
                    "POST",
                    provider.api_url,
                    headers={
                        "Authorization": f"Bearer {provider.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                ) as resp:
                    resp.raise_for_status()

                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                                if chunk.get("choices"):
                                    delta = chunk["choices"][0].get("delta", {})
                                    token = delta.get("content") or delta.get("reasoning_content") or ""
                                    if token:
                                        full_text += token
                                        yield {"type": "token", "token": token}

                                if chunk.get("usage"):
                                    usage = chunk["usage"]
                                    prompt_tokens = usage.get("prompt_tokens", 0)
                                    completion_tokens = usage.get("completion_tokens", 0)
                                    total_tokens = usage.get("total_tokens", 0)
                            except json.JSONDecodeError:
                                continue

        except Exception as _exc:
            _duration = (time.monotonic() - _start) * 1000
            await token_store.record(UsageRecord(
                function_name=_caller,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                model=provider.model,
                timestamp=time.time(),
                success=False,
                duration_ms=round(_duration, 1),
                error_message=str(_exc),
                provider=provider.id,
            ))
            last_exc = _exc
            logger.warning(
                "[LLM] Stream provider %s failed after %.1fs: %s",
                provider.id, _duration / 1000, _exc,
            )
            # If we yielded any tokens, we're committed \u2014 propagate error
            if full_text:
                yield {"type": "error", "error": str(_exc)}
                return
            # Otherwise try next provider
            continue

        # Success: record and yield done
        _duration = (time.monotonic() - _start) * 1000
        await token_store.record(UsageRecord(
            function_name=_caller,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            model=provider.model,
            timestamp=time.time(),
            success=True,
            duration_ms=round(_duration, 1),
            provider=provider.id,
        ))

        yield {
            "type": "done",
            "full_text": full_text,
            "usage": {
                "model": provider.model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "latency_ms": round(_duration, 1),
            }
        }
        return

    # All providers exhausted
    if last_exc is None:
        last_exc = RuntimeError("No LLM providers available")
    yield {"type": "error", "error": str(last_exc)}
'''

# Ensure the replacement ends with exactly the right number of newlines
# We keep the newline at the end so the next function is still on the right line
old_stream_source = "".join(lines[s_start:s_end])
new_stream_source = new_stream

# Replace the lines
lines[s_start:s_end] = [new_stream_source]

# ---- Replacement 2: llm_complete_with_system ----
# Re-parse to get updated ranges for the next function
# Since we've modified lines, we need to recalculate
new_source = "".join(lines)
tree2 = ast.parse(new_source)
ws_start, ws_end = None, None
for node in ast.walk(tree2):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "llm_complete_with_system":
        ws_start = node.lineno - 1
        ws_end = node.end_lineno
        break

if ws_start is None:
    print("ERROR: llm_complete_with_system not found after first replacement", file=sys.stderr)
    sys.exit(1)

print(f"  llm_complete_with_system updated range: lines {ws_start+1}-{ws_end}", file=sys.stderr)

new_ws = '''async def llm_complete_with_system(system_prompt: str, prompt: str, response_format: dict | None = None, force_json: bool = False) -> str:
    """Call LLM with a custom system prompt, with provider failover."""
    import httpx
    await _check_key()

    _caller = sys._getframe(1).f_code.co_name
    providers = get_configured_providers()
    last_exc: Exception | None = None

    for provider in providers:
        body = {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 8192,
        }
        if response_format:
            body["response_format"] = response_format
        elif force_json:
            body["response_format"] = {"type": "json_object"}

        _start = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=provider.timeout, trust_env=False
            ) as client:
                resp = await client.post(
                    provider.api_url,
                    headers={
                        "Authorization": f"Bearer {provider.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                message = data["choices"][0]["message"]
                content = message.get("content", "")
                if not content:
                    content = message.get("reasoning_content", "")

                usage = data.get("usage", {})
                _duration = (time.monotonic() - _start) * 1000
                await token_store.record(UsageRecord(
                    function_name=_caller,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    model=provider.model,
                    timestamp=time.time(),
                    success=True,
                    duration_ms=round(_duration, 1),
                    provider=provider.id,
                ))
                return content
        except Exception as _exc:
            _duration = (time.monotonic() - _start) * 1000
            await token_store.record(UsageRecord(
                function_name=_caller,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                model=provider.model,
                timestamp=time.time(),
                success=False,
                duration_ms=round(_duration, 1),
                error_message=str(_exc),
                provider=provider.id,
            ))
            last_exc = _exc
            logger.warning(
                "[LLM] Provider %s failed after %.1fs: %s",
                provider.id, _duration / 1000, _exc,
            )
            continue

    if last_exc is None:
        raise RuntimeError("No LLM providers available")
    raise last_exc
'''

lines[ws_start:ws_end] = [new_ws]

# ---- Write back ----
final = "".join(lines)
with open(FILE, "w", encoding="utf-8") as f:
    f.write(final)

# Verify syntax
try:
    ast.parse(final)
    print("OK: Syntax valid", file=sys.stderr)
except SyntaxError as e:
    print(f"ERROR: Syntax error after transformation: {e}", file=sys.stderr)
    sys.exit(1)

print("Done", file=sys.stderr)
