"""Tool functions for Agent Framework"""
import json
import os
import re
import subprocess
import httpx
import time
from pathlib import Path
from typing import Optional

from ._constants import WORKDIR


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
MAX_REDIRECTS = 5


def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str) -> str:
    """Execute a bash command with security checks.

    Security checks:
    - Pattern-based dangerous command detection (60+ patterns)
    - Per-session and permanent allowlists
    - Smart approval via LLM for uncertain cases
    - YOLO bypass mode

    Args:
        command: The shell command to execute

    Returns:
        Command output or error message
    """
    # Import here to avoid circular dependency
    try:
        from .security import check_bash_security
    except ImportError:
        # Fallback to old behavior if security module not available
        dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
        if any(d in command for d in dangerous):
            return "Error: Dangerous command blocked"

    # Check security - get session key from environment if available
    session_key = os.getenv("AGENT_SESSION_KEY", "default")
    approved, error_msg = check_bash_security(command, session_key=session_key)

    if not approved:
        print(f"[DEBUG bash] blocked: {error_msg}")
        return f"Error: {error_msg}"

    # Execute command
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except Exception as e:
        return f"Error: {e}"


def run_read(path: str, limit: int = None) -> str:
    try:
        lines = safe_path(path).read_text(encoding="utf-8").splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        c = fp.read_text(encoding="utf-8")
        if old_text not in c:
            return f"Error: Text not found in {path}"
        fp.write_text(c.replace(old_text, new_text, 1), encoding="utf-8")
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


def _strip_tags(text: str) -> str:
    """Remove HTML tags, scripts, styles, and decode entities."""
    if not text:
        return ""
    import re
    import html
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.I)
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'\[[\U0001F300-\U0001F9FF]+\]', '', text)
    text = re.sub(r'\[[^]]{1,10}\]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _normalize(text: str) -> str:
    """Normalize whitespace."""
    import re
    text = re.sub(r'[ \t]+', ' ', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _validate_url(url: str) -> tuple[bool, str]:
    """Validate URL: must be http(s) with valid domain."""
    from urllib.parse import urlparse
    try:
        p = urlparse(url)
        if p.scheme not in ('http', 'https'):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
        if not p.netloc:
            return False, "Missing domain"
        return True, ""
    except Exception as e:
        return False, str(e)


def _to_markdown(html_text: str) -> str:
    """Convert HTML to markdown."""
    import re
    text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
                  lambda m: f'[{_strip_tags(m[2])}]({m[1]})', html_text, flags=re.I)
    text = re.sub(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
                  lambda m: f'\n{"#" * int(m[1])} {_strip_tags(m[2])}\n', text, flags=re.I)
    text = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {_strip_tags(m[1])}', text, flags=re.I)
    text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
    text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
    return _normalize(_strip_tags(text))


def run_web_search(query: str, num_results: int = 5) -> str:
    """MiniMax web search - Search the internet for information.

    Note: This function returns search result metadata only (URLs, titles, descriptions).
    To get full content from specific URLs, use web_fetch tool after search.
    For structured data (e.g., flight schedules, prices), always follow up with web_fetch
    to retrieve and parse the actual page content.

    错误分类:
    - [FATAL_ERROR] 搜索API不可用 -> 请改用其他方式或告知用户
    - 错误: 未设置API密钥 -> 检查环境变量
    - 错误: 搜索请求超时 -> 可以重试
    """
    print(f"[DEBUG web_search] query={query}, num_results={num_results}")

    minimax_key = os.getenv("MINIMAX_API_KEY", "")
    auth_token = os.getenv("ANTHROPIC_AUTH_TOKEN", "")

    if minimax_key and minimax_key not in ("ANTHROPIC_AUTH_TOKEN", "your_key_here", ""):
        api_key = minimax_key
    else:
        api_key = auth_token

    base_url = os.getenv("MINIMAX_API_HOST") or "https://api.minimaxi.com"

    if not api_key:
        return "错误: 未设置API密钥"

    try:
        start_time = time.time()
        with httpx.Client() as client:
            response = client.post(
                f"{base_url}/v1/coding_plan/search",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={"q": query},
                timeout=30.0
            )
        duration = time.time() - start_time
        print(f"[DEBUG web_search] response.status={response.status_code}, duration={duration:.2f}s")

        if response.status_code != 200:
            return f"错误: API返回 {response.status_code} - {response.text[:200]}"

        result = response.json()
        base_resp = result.get("base_resp", {})
        if base_resp.get("status_code") != 0:
            error_msg = base_resp.get('status_msg', '未知错误')
            return f"[FATAL_ERROR] 搜索API不可用: {error_msg}，请改用其他方式获取信息或告诉用户搜索功能暂时不可用"
        organic = result.get("organic", [])
        if not organic:
            return "未找到相关结果"

        lines = []
        for i, item in enumerate(organic[:num_results], 1):
            title = _strip_tags(item.get("title", "无标题"))
            link = item.get("link", "")
            snippet = _strip_tags(item.get("snippet", ""))[:200]
            lines.append(f"{i}. {title}\n   {link}\n   {snippet}\n")
        print(f"[DEBUG web_search] 返回 {len(lines)} 条结果")
        return "\n".join(lines)

    except httpx.TimeoutException:
        return "错误: 搜索请求超时"
    except Exception as e:
        return f"错误: {str(e)}"


def run_web_fetch(url: str, max_chars: int = 50000) -> str:
    """Fetch URL and extract readable content."""
    print(f"[DEBUG web_fetch] url={url}, max_chars={max_chars}")

    is_valid, error_msg = _validate_url(url)
    if not is_valid:
        return f"URL验证失败: {error_msg}"

    try:
        start_time = time.time()
        with httpx.Client(follow_redirects=True, max_redirects=MAX_REDIRECTS, timeout=30.0) as client:
            r = client.get(url, headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
        duration = time.time() - start_time
        print(f"[DEBUG web_fetch] status={r.status_code}, final_url={r.url}, duration={duration:.2f}s")

        ctype = r.headers.get("content-type", "")

        if "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<html")):
            try:
                from readability import Document
                doc = Document(r.text)
                content = _to_markdown(doc.summary())
                title = doc.title() if doc.title() else ""
                text = f"# {title}\n\n{content}" if title else content
            except ImportError:
                text = _to_markdown(r.text)
            extractor = "html"
        else:
            text = r.text
            extractor = "raw"

        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars]

        result = json.dumps({
            "url": url,
            "finalUrl": str(r.url),
            "status": r.status_code,
            "extractor": extractor,
            "truncated": truncated,
            "length": len(text),
            "text": text
        }, ensure_ascii=False)

        print(f"[DEBUG web_fetch] 返回长度={len(result)}, truncated={truncated}")
        return result

    except httpx.TimeoutException:
        return f"错误: 请求超时"
    except Exception as e:
        return f"错误: {str(e)}"


def _write_judge_log(message: str):
    """Write debug log to file"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "judge_debug.log"
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")


def judge_tool(pass_: bool, advice: str = "") -> str:
    """Tool for reporting judgment result with optional advice."""
    _write_judge_log(f"judge_tool called with pass_={pass_}, advice={advice[:100] if advice else 'none'}")
    return json.dumps({"pass": pass_, "verdict": "pass" if pass_ else "fail", "advice": advice})


# judge tool schema for LLM (Enhanced with verdict types)
JUDGE_TOOL_SCHEMA = {
    "name": "judge_tool",
    "description": "Report whether the tool results successfully solved the user's problem, and provide advice if not solved.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["pass", "partial", "fail", "escalate"],
                "description": "Judgment verdict: pass=fully solved, partial=partially solved, fail=not solved, escalate=needs human"
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Confidence in the verdict (0.0-1.0)"
            },
            "advice": {
                "type": "string",
                "description": "Next step guidance if not fully solved (empty if verdict=pass)"
            },
            "summary": {
                "type": "string",
                "description": "Brief explanation of the verdict"
            }
        },
        "required": ["verdict", "confidence", "advice", "summary"]
    }
}


def run_judge(tool_results: str, user_prompt: str) -> tuple[bool, str]:
    """Sub-agent to judge tool results. Returns (pass: bool, advice: str).

    The LLM MUST call judge_tool to report the verdict.
    pass=True means tool results solved the problem, False means not solved.
    advice contains explanation text that can be shown to the user.
    """
    print(f"[DEBUG judge] 开始评估 | tool_results_len={len(tool_results)}, user_prompt_len={len(user_prompt)}")
    _write_judge_log(f"run_judge called: tool_results len={len(tool_results)}, user_prompt len={len(user_prompt)}")

    auth_token = os.getenv("ANTHROPIC_AUTH_TOKEN", "")
    base_url = os.getenv("ANTHROPIC_API_HOST") or os.getenv("ANTHROPIC_BASE_URL") or "https://api.minimaxi.com/anthropic/"

    if not auth_token:
        print("[DEBUG judge] 无 auth_token，返回 (False, '')")
        _write_judge_log("No auth_token, returning (False, '')")
        return False, ""

    import anthropic
    from datetime import datetime
    client = anthropic.Anthropic(api_key=auth_token, base_url=base_url)

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    system_prompt = f"""你是一个很严厉的评估员,只有在你没有建议时才会给出 "pass" 的评判, 其他情况都应该给出 "fail" 或 "partial" 的评判, 并且提供详细的改进建议。请严格评估以下工具结果是否完全解决了用户的问题，并给出具体的改进建议（如果没有完全解决）。评估时请考虑以下维度：

## 评估框架
从以下维度评估是否完成了用户任务,有一个维度不符合及判定为 fail:
1. **完整性 (Completeness)**: 结果是否完全回答了请求？
2. **正确性 (Correctness)**: 结果是否是最新的内容，准确有效？
3. **相关性 (Relevance)**: 结果是否直接针对用户问题，没有偏离任务的内容？
4. **充分性 (Sufficiency)**: 是否需要额外信息，用户任务描述的隐含内容是否都被覆盖了？
5. **起因 经过 结果 (Cause-Process-Outcome)**: 结果是否清晰展示了问题的起因、处理过程和最终结果？

## Verdict 类型
- `pass`: 没有任何建议给pass
- `fail`: 除pass情况外所有情况都给fail

## 输出要求
必须调用 judge_tool：
- verdict: "pass" | "fail"
- confidence: 0.0-1.0
- advice: 下一步指导（pass 时为空）
- summary: 判决简要说明

You MUST call the judge_tool with your verdict."""

    try:
        messages = [
            {"role": "user", "content": f"User question: {user_prompt}\n\nTool results:\n{tool_results[:3000]}"}
        ]

        max_retries = 5
        retry_count = 0

        while retry_count < max_retries:
            start_time = time.time()
            response = client.messages.create(
                model="MiniMax-M2.7",
                max_tokens=1000,
                system=system_prompt,
                messages=messages,
                tools=[JUDGE_TOOL_SCHEMA]
            )
            duration = time.time() - start_time
            print(f"[DEBUG judge] LLM 调用完成 | retry={retry_count}, duration={duration:.2f}s, stop_reason={response.stop_reason}")

            # Check if LLM called judge_tool
            for block in response.content:
                if block.type == "tool_use" and block.name == "judge_tool":
                    verdict = block.input.get("verdict", "fail")
                    confidence = block.input.get("confidence", 0.0)
                    advice = block.input.get("advice", "")
                    summary = block.input.get("summary", "")
                    print(f"[DEBUG judge] LLM verdict={verdict}, confidence={confidence}, advice={advice[:50] if advice else 'empty'}...")
                    _write_judge_log(f"LLM called judge_tool with verdict={verdict}, confidence={confidence}")
                    # If advice is non-empty, return False regardless of verdict (has improvement suggestions)
                    if advice:
                        return False, advice
                    return verdict in ("pass", "partial"), advice

            # LLM did not call judge_tool, add response to messages and retry
            retry_count += 1
            print(f"[DEBUG judge] 未调用 judge_tool，重试 ({retry_count}/{max_retries})")
            _write_judge_log(f"No judge_tool call, retry {retry_count}/{max_retries}")

            # Add LLM response to messages for context
            for block in response.content:
                if hasattr(block, 'text'):
                    messages.append({"role": "assistant", "content": block.text})
                    messages.append({"role": "user", "content": f"你没有使用 judge_tool，这是第 {retry_count} 次提醒。请使用 judge_tool 提交评估结果，格式：verdict=\"pass\"或\"fail\"，confidence=0.0-1.0，advice=下一步指导。"})
                    break

        _write_judge_log(f"Max retries ({max_retries}) reached, returning (False, '')")
        return False, ""

    except Exception as e:
        _write_judge_log(f"Exception: {type(e).__name__}: {e}")
        return False, ""


def run_text_to_image(prompt: str, aspect_ratio: str = "1:1", output_path: str = "generated_image.png") -> str:
    """Generate image from text using MiniMax API"""
    import base64

    minimax_key = os.getenv("MINIMAX_API_KEY", "")
    auth_token = os.getenv("ANTHROPIC_AUTH_TOKEN", "")

    if minimax_key and minimax_key not in ("ANTHROPIC_AUTH_TOKEN", "your_key_here", ""):
        api_key = minimax_key
    else:
        api_key = auth_token

    base_url = os.getenv("MINIMAX_API_HOST") or "https://api.minimaxi.com"

    if not api_key:
        return json.dumps({"type": "error", "message": "错误: 未设置API密钥"})

    try:
        response = httpx.post(
            f"{base_url}/v1/image_generation",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "image-01",
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "response_format": "base64",
            },
            timeout=120.0
        )

        if response.status_code != 200:
            return json.dumps({"type": "error", "message": f"错误: API返回 {response.status_code} - {response.text[:200]}"})

        result = response.json()
        images = result.get("data", {}).get("image_base64", [])

        if not images:
            return json.dumps({"type": "error", "message": "错误: 未生成图片"})

        image_data = base64.b64decode(images[0])
        fp = safe_path(output_path)
        fp.write_bytes(image_data)

        ext = output_path.lower().split('.')[-1]
        if ext == 'jpg' or ext == 'jpeg':
            mime_type = 'image/jpeg'
        elif ext == 'png':
            mime_type = 'image/png'
        elif ext == 'gif':
            mime_type = 'image/gif'
        elif ext == 'webp':
            mime_type = 'image/webp'
        else:
            mime_type = 'image/png'

        image_data_url = f"data:{mime_type};base64,{images[0]}"
        return json.dumps({
            "type": "image",
            "message": f"图片已生成并保存到: {output_path}\n提示词: {prompt}\n尺寸比例: {aspect_ratio}",
            "image": image_data_url,
            "path": output_path
        })

    except httpx.TimeoutException:
        return json.dumps({"type": "error", "message": "错误: 图片生成请求超时"})
    except Exception as e:
        return f"错误: {str(e)}"