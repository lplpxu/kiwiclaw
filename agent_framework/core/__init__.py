"""Agent Framework Core Module"""
import os
import json
import subprocess
import time
import uuid
import threading
import re
import httpx
from pathlib import Path
from queue import Queue
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from dotenv import load_dotenv
load_dotenv(override=True)

WORKDIR = Path.cwd()

# === Configuration ===
from ..config.settings import Settings, AgentConfig, SandboxConfig, MCPConfig, settings

# === Tool System ===
from .tool import tool, Tool as BaseTool, ToolRegistry

# === Anthropic Client ===
from anthropic import Anthropic

# Support both ANTHROPIC_API_KEY and ANTHROPIC_AUTH_TOKEN (Windows/system env)
api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
base_url = os.getenv("ANTHROPIC_BASE_URL") or os.getenv("ANTHROPIC_BASE_URL")

client = Anthropic(
    base_url=base_url if base_url else None,
    api_key=api_key
)
MODEL = os.getenv("MODEL_ID", "claude-sonnet-4-20250514")

# === Constants ===
TOKEN_THRESHOLD = int(os.getenv("TOKEN_THRESHOLD", "100000"))
POLL_INTERVAL = 5
IDLE_TIMEOUT = 60

# === Soul Prompts ===
SOUL_PROMPTS = {}

def load_soul_prompts():
    """Load prompts from soud.md file"""
    global SOUL_PROMPTS
    soul_path = WORKDIR / "soud.md"
    if not soul_path.exists():
        SOUL_PROMPTS = {"simple": "你是我的助手", "deep": "思考任务流程所涉原理和步骤，并列出来", "plan": "思考任务流程所涉及原理、步骤和主体，并列出来，做出计划详细步骤", "debug": "思考任务流程所涉及的所有主体，用三现两原原则分析问题，列出来所有主体和可能问题，逐一验证"}
        return

    content = soul_path.read_text(encoding="utf-8")
    current_section = None
    current_content = []

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if current_section is not None:
                SOUL_PROMPTS[current_section] = "\n".join(current_content).strip()
            current_section = stripped.lstrip("#").strip().lower()
            current_content = []
        elif current_section is not None:
            current_content.append(line)

    if current_section is not None:
        SOUL_PROMPTS[current_section] = "\n".join(current_content).strip()

    # defaults
    if "simple" not in SOUL_PROMPTS:
        SOUL_PROMPTS["simple"] = "你是我的助手"
    if "deep" not in SOUL_PROMPTS:
        SOUL_PROMPTS["deep"] = "思考任务流程所涉原理和步骤，并列出来"
    if "plan" not in SOUL_PROMPTS:
        SOUL_PROMPTS["plan"] = "思考任务流程所涉及原理、步骤和主体，并列出来，做出计划详细步骤"
    if "debug" not in SOUL_PROMPTS:
        SOUL_PROMPTS["debug"] = "思考任务流程所涉及的所有主体，用三现两原原则分析问题，列出来所有主体和可能问题，逐一验证"

# Load prompts on import
load_soul_prompts()


# === Tool Base ===
@dataclass
class Tool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: callable
    enabled: bool = True


# === Core Functions ===
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


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


def run_web_search(query: str, num_results: int = 5) -> str:
    """MiniMax web search - 搜索互联网获取相关信息"""
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

            if response.status_code != 200:
                return f"错误: API返回 {response.status_code} - {response.text[:200]}"

            result = response.json()
            # 格式化结果
            organic = result.get("organic", [])
            if not organic:
                return "未找到相关结果"

            lines = []
            for i, item in enumerate(organic[:num_results], 1):
                title = item.get("title", "无标题")
                link = item.get("link", "")
                snippet = item.get("snippet", "")[:200]
                lines.append(f"{i}. {title}\n   {link}\n   {snippet}\n")
            return "\n".join(lines)

    except httpx.TimeoutException:
        return "错误: 搜索请求超时"
    except Exception as e:
        return f"错误: {str(e)}"


def run_text_to_image(prompt: str, aspect_ratio: str = "1:1", output_path: str = "generated_image.png") -> str:
    """Generate image from text using MiniMax API"""
    import base64
    import httpx

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

        # Decode and save the first image
        image_data = base64.b64decode(images[0])
        fp = safe_path(output_path)
        fp.write_bytes(image_data)

        # Determine image format from extension
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

        # Return JSON with image data URL
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


# === TodoManager ===
class TodoManager:
    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
        validated, ip = [], 0
        for i, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            af = str(item.get("activeForm", "")).strip()
            if not content:
                raise ValueError(f"Item {i}: content required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {i}: invalid status '{status}'")
            if not af:
                raise ValueError(f"Item {i}: activeForm required")
            if status == "in_progress":
                ip += 1
            validated.append({"content": content, "status": status, "activeForm": af})
        if len(validated) > 20:
            raise ValueError("Max 20 todos")
        if ip > 1:
            raise ValueError("Only one in_progress allowed")
        self.items = validated
        return self.render()

    def render(self) -> str:
        if not self.items:
            return "No todos."
        lines = []
        for item in self.items:
            m = {"completed": "[x]", "in_progress": "[>]", "pending": "[ ]"}.get(item["status"], "[?]")
            suffix = f" <- {item['activeForm']}" if item["status"] == "in_progress" else ""
            lines.append(f"{m} {item['content']}{suffix}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)

    def has_open_items(self) -> bool:
        return any(item.get("status") != "completed" for item in self.items)


# === TaskManager ===
TASKS_DIR = WORKDIR / ".tasks"

class TaskManager:
    def __init__(self):
        TASKS_DIR.mkdir(exist_ok=True)

    def _next_id(self) -> int:
        ids = [int(f.stem.split("_")[1]) for f in TASKS_DIR.glob("task_*.json")]
        return max(ids, default=0) + 1

    def _load(self, tid: int) -> dict:
        p = TASKS_DIR / f"task_{tid}.json"
        if not p.exists():
            raise ValueError(f"Task {tid} not found")
        return json.loads(p.read_text())

    def _save(self, task: dict):
        (TASKS_DIR / f"task_{task['id']}.json").write_text(json.dumps(task, indent=2))

    def create(self, subject: str, description: str = "") -> str:
        task = {"id": self._next_id(), "subject": subject, "description": description,
                "status": "pending", "owner": None, "blockedBy": [], "blocks": []}
        self._save(task)
        return json.dumps(task, indent=2)

    def get(self, tid: int) -> str:
        return json.dumps(self._load(tid), indent=2)

    def update(self, tid: int, status: str = None,
               add_blocked_by: list = None, add_blocks: list = None) -> str:
        task = self._load(tid)
        if status:
            task["status"] = status
            if status == "completed":
                for f in TASKS_DIR.glob("task_*.json"):
                    t = json.loads(f.read_text())
                    if tid in t.get("blockedBy", []):
                        t["blockedBy"].remove(tid)
                        self._save(t)
            if status == "deleted":
                (TASKS_DIR / f"task_{tid}.json").unlink(missing_ok=True)
                return f"Task {tid} deleted"
        if add_blocked_by:
            task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
        if add_blocks:
            task["blocks"] = list(set(task["blocks"] + add_blocks))
        self._save(task)
        return json.dumps(task, indent=2)

    def list_all(self) -> str:
        tasks = [json.loads(f.read_text()) for f in sorted(TASKS_DIR.glob("task_*.json"))]
        if not tasks:
            return "No tasks."
        lines = []
        for t in tasks:
            m = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}.get(t["status"], "[?]")
            owner = f" @{t['owner']}" if t.get("owner") else ""
            blocked = f" (blocked by: {t['blockedBy']})" if t.get("blockedBy") else ""
            lines.append(f"{m} #{t['id']}: {t['subject']}{owner}{blocked}")
        return "\n".join(lines)

    def claim(self, tid: int, owner: str) -> str:
        task = self._load(tid)
        task["owner"] = owner
        task["status"] = "in_progress"
        self._save(task)
        return f"Claimed task #{tid} for {owner}"


# === BackgroundManager ===
BG_TASKS = {}
BG_NOTIFICATIONS = Queue()

class BackgroundManager:
    def run(self, command: str, timeout: int = 120) -> str:
        tid = str(uuid.uuid4())[:8]
        BG_TASKS[tid] = {"status": "running", "command": command, "result": None}
        threading.Thread(target=self._exec, args=(tid, command, timeout), daemon=True).start()
        return f"Background task {tid} started: {command[:80]}"

    def _exec(self, tid: str, command: str, timeout: int):
        try:
            r = subprocess.run(command, shell=True, cwd=WORKDIR,
                               capture_output=True, text=True, timeout=timeout)
            output = (r.stdout + r.stderr).strip()[:50000]
            BG_TASKS[tid].update({"status": "completed", "result": output or "(no output)"})
        except Exception as e:
            BG_TASKS[tid].update({"status": "error", "result": str(e)})
        BG_NOTIFICATIONS.put({"task_id": tid, "status": BG_TASKS[tid]["status"],
                              "result": BG_TASKS[tid]["result"][:500]})

    def check(self, tid: str = None) -> str:
        if tid:
            t = BG_TASKS.get(tid)
            return f"[{t['status']}] {t.get('result', '(running)')}" if t else f"Unknown: {tid}"
        return "\n".join(f"{k}: [{v['status']}] {v['command'][:60]}" for k, v in BG_TASKS.items()) or "No bg tasks."

    def drain(self) -> list:
        notifs = []
        while not BG_NOTIFICATIONS.empty():
            notifs.append(BG_NOTIFICATIONS.get_nowait())
        return notifs


# === MessageBus ===
TEAM_DIR = WORKDIR / ".team"
INBOX_DIR = TEAM_DIR / "inbox"

class MessageBus:
    def __init__(self):
        INBOX_DIR.mkdir(parents=True, exist_ok=True)

    def send(self, sender: str, to: str, content: str,
             msg_type: str = "message", extra: dict = None) -> str:
        msg = {"type": msg_type, "from": sender, "content": content,
               "timestamp": time.time()}
        if extra:
            msg.update(extra)
        with open(INBOX_DIR / f"{to}.jsonl", "a") as f:
            f.write(json.dumps(msg) + "\n")
        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> list:
        path = INBOX_DIR / f"{name}.jsonl"
        if not path.exists():
            return []
        msgs = [json.loads(l) for l in path.read_text().strip().splitlines() if l]
        path.write_text("")
        return msgs

    def broadcast(self, sender: str, content: str, names: list) -> str:
        count = 0
        for n in names:
            if n != sender:
                self.send(sender, n, content, "broadcast")
                count += 1
        return f"Broadcast to {count} teammates"


# === Compression ===
TRANSCRIPT_DIR = WORKDIR / ".transcripts"

def estimate_tokens(messages: list) -> int:
    return len(json.dumps(messages, default=str)) // 4

def microcompact(messages: list):
    indices = []
    for i, msg in enumerate(messages):
        if msg["role"] == "user" and isinstance(msg.get("content"), list):
            for part in msg["content"]:
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    indices.append(part)
    if len(indices) <= 3:
        return
    for part in indices[:-3]:
        if isinstance(part.get("content"), str) and len(part["content"]) > 100:
            part["content"] = "[cleared]"

def auto_compact(messages: list) -> list:
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    conv_text = json.dumps(messages, default=str)[:80000]
    prompt = f"""请提炼以下对话的关键信息，包括：
1. 对话的核心主题和目标
2. 已完成的重要结论或决定
3. 未解决的关键问题
4. 保持继续对话所需的重要上下文

对话内容：
{conv_text}

请用简洁的结构化方式输出关键信息摘要。"""
    resp = client.messages.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=3000,
    )
    summary = resp.content[0].text
    return [
        {"role": "user", "content": f"[Compressed. Transcript saved: {path}]\n--- 关键信息摘要 ---\n{summary}\n--- 继续对话 ---"},
        {"role": "assistant", "content": "已收到对话摘要，我将基于关键信息继续对话。"},
    ]


# === Global Instances ===
TODO = TodoManager()
TASK_MGR = TaskManager()
BG = BackgroundManager()
BUS = MessageBus()


# === Agent ===
class Agent:
    """Agent with full tool set like s_full.py"""

    def __init__(self, name: str = "agent", config: Optional[AgentConfig] = None):
        self.name = name
        self.config = config or AgentConfig(name=name)
        self.messages: list = []
        self._tools = self._build_tools()
        self._tool_handlers = self._build_handlers()
        # Load soul.md prompts on agent startup
        load_soul_prompts()
        self._current_mode = getattr(self.config, 'mode', 'simple')

    def _build_tools(self) -> list:
        return [
            {"name": "bash", "description": "Run shell command.",
             "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
            {"name": "read_file", "description": "Read file.",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
            {"name": "write_file", "description": "Write file.",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
            {"name": "edit_file", "description": "Edit file.",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
            {"name": "TodoWrite", "description": "Update todo list.",
             "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {"content": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}, "activeForm": {"type": "string"}}}}}, "required": ["items"]}},
            {"name": "task_create", "description": "Create task.",
             "input_schema": {"type": "object", "properties": {"subject": {"type": "string"}, "description": {"type": "string"}}, "required": ["subject"]}},
            {"name": "task_get", "description": "Get task.",
             "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
            {"name": "task_update", "description": "Update task.",
             "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}, "status": {"type": "string"}}, "required": ["task_id"]}},
            {"name": "task_list", "description": "List tasks.",
             "input_schema": {"type": "object", "properties": {}}},
            {"name": "background_run", "description": "Run in background.",
             "input_schema": {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer"}}, "required": ["command"]}},
            {"name": "check_background", "description": "Check bg task.",
             "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}}},
            {"name": "compress", "description": "Compress context.", "input_schema": {"type": "object", "properties": {}}},
            {"name": "web_search", "description": "MiniMax web search - Search the internet for information.",
             "input_schema": {"type": "object", "properties": {"query": {"type": "string", "description": "搜索关键词"}, "num_results": {"type": "integer", "description": "返回结果数量", "default": 5}}, "required": ["query"]}},
            {"name": "text_to_image", "description": "Generate image from text prompt using MiniMax AI. Returns base64 encoded image data.",
             "input_schema": {"type": "object", "properties": {
                 "prompt": {"type": "string", "description": "图像生成描述词"},
                 "aspect_ratio": {"type": "string", "description": "图片比例，如16:9, 1:1, 9:16", "default": "1:1"},
                 "output_path": {"type": "string", "description": "输出文件路径，如image.png", "default": "generated_image.png"}
             }, "required": ["prompt"]}},
        ]

    def _build_handlers(self) -> dict:
        return {
            "bash": lambda **kw: run_bash(kw["command"]),
            "read_file": lambda **kw: run_read(kw["path"], kw.get("limit")),
            "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
            "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
            "TodoWrite": lambda **kw: TODO.update(kw["items"]),
            "task_create": lambda **kw: TASK_MGR.create(kw["subject"], kw.get("description", "")),
            "task_get": lambda **kw: TASK_MGR.get(kw["task_id"]),
            "task_update": lambda **kw: TASK_MGR.update(kw["task_id"], kw.get("status")),
            "task_list": lambda **kw: TASK_MGR.list_all(),
            "background_run": lambda **kw: BG.run(kw["command"], kw.get("timeout", 120)),
            "check_background": lambda **kw: BG.check(kw.get("task_id")),
            "compress": lambda **kw: "Compressing...",
            "web_search": lambda **kw: run_web_search(kw["query"], kw.get("num_results", 5)),
            "text_to_image": lambda **kw: run_text_to_image(kw["prompt"], kw.get("aspect_ratio", "1:1"), kw.get("output_path", "generated_image.png")),
        }

    def get_system_prompt(self) -> str:
        mode = getattr(self.config, 'mode', 'simple')
        # Reload prompts when mode changes or on first call
        if mode != self._current_mode:
            load_soul_prompts()
            self._current_mode = mode
        # Get current time
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        time_prefix = f"[系统时间: {current_time}]\n\n"
        if mode == 'simple':
            return time_prefix + SOUL_PROMPTS.get("simple", "你是我的助手")
        elif mode == 'deep':
            return time_prefix + SOUL_PROMPTS.get("deep", "思考任务流程所涉原理和步骤，并列出来")
        elif mode == 'plan':
            return time_prefix + SOUL_PROMPTS.get("plan", "思考任务流程所涉及原理、步骤和主体，并列出来，做出计划详细步骤")
        elif mode == 'debug':
            return time_prefix + SOUL_PROMPTS.get("debug", "思考任务流程所涉及的所有主体，用三现两原原则分析问题，列出来所有主体和可能问题，逐一验证")
        else:
            return time_prefix + SOUL_PROMPTS.get("simple", "你是我的助手")

    async def think(self, prompt: str) -> str:
        """Main thinking loop"""
        self.messages.append({"role": "user", "content": prompt})

        while True:
            # Compression
            microcompact(self.messages)
            if estimate_tokens(self.messages) > TOKEN_THRESHOLD:
                print("[auto-compact triggered]")
                self.messages[:] = auto_compact(self.messages)

            # Drain background notifications
            notifs = BG.drain()
            if notifs:
                txt = "\n".join(f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs)
                self.messages.append({"role": "user", "content": f"<background-results>\n{txt}\n</background-results>"})

            # Filter out image_data from messages before sending to LLM
            llm_messages = []
            for msg in self.messages:
                if msg.get("image_data"):
                    # Has image - keep text content only, remove base64
                    text_content = msg.get("content", "")
                    if text_content:
                        llm_messages.append({"role": msg["role"], "content": text_content})
                elif isinstance(msg.get("content"), list):
                    # Handle content blocks - extract text only
                    text_parts = []
                    for part in msg["content"]:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part["text"])
                    if text_parts:
                        llm_messages.append({"role": msg["role"], "content": "\n".join(text_parts)})
                else:
                    llm_messages.append(msg)

            # LLM call - include system prompt as first message in conversation
            system_msg = {"role": "system", "content": self.get_system_prompt()}
            all_messages = [system_msg] + llm_messages
            response = client.messages.create(
                model=self.config.model,
                messages=all_messages,
                tools=self._tools,
                max_tokens=8000,
            )
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                return "".join(b.text for b in response.content if hasattr(b, 'text')) or "(no response)"

            # Tool execution
            results = []
            manual_compress = False
            image_result = None  # Track if text_to_image was called
            for block in response.content:
                if block.type == "tool_use":
                    if block.name == "compress":
                        manual_compress = True
                    handler = self._tool_handlers.get(block.name)
                    try:
                        output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                    except Exception as e:
                        output = f"Error: {e}"
                    print(f"> {block.name}: {str(output)[:200]}")

                    # Check if this is a text_to_image result with image data
                    if block.name == "text_to_image":
                        try:
                            img_data = json.loads(output)
                            if img_data.get("type") == "image" and img_data.get("image"):
                                image_result = img_data
                        except:
                            pass

                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})

            self.messages.append({"role": "user", "content": results})

            # If text_to_image was called, return the image data directly
            if image_result:
                return json.dumps(image_result)

            if manual_compress:
                print("[manual compact]")
                self.messages[:] = auto_compact(self.messages)


# === Export ===
__all__ = [
    "Agent", "AgentConfig", "Tool", "ToolRegistry",
    "TodoManager", "TaskManager", "BackgroundManager", "MessageBus",
    "TODO", "TASK_MGR", "BG", "BUS",
    "run_bash", "run_read", "run_write", "run_edit",
    "microcompact", "auto_compact", "estimate_tokens",
    "AgentRunner", "DockerSandbox", "SandboxConfig",
    "MCPServer", "MCPClient",
]


# === AgentRunner ===
class AgentRunner:
    """Manages agent lifecycle"""
    def __init__(self, agent: Agent, sandbox_config: "SandboxConfig" = None):
        self.agent = agent
        self.sandbox = None
        self.sandbox_config = sandbox_config
        self._running = False

    async def start(self):
        self._running = True
        if self.agent.config.sandbox_enabled and self.sandbox_config:
            self.sandbox = DockerSandbox(self.sandbox_config)
            await self.sandbox.create()

    async def stop(self):
        self._running = False
        if self.sandbox:
            await self.sandbox.destroy()
            self.sandbox = None

    async def run_task(self, prompt: str) -> str:
        return await self.agent.think(prompt)


# === Docker Sandbox ===
import docker

@dataclass
class SandboxConfig:
    image: str = "python:3.11-slim"
    cpu_limit: str = "1.0"
    memory_limit: str = "512m"
    network_disabled: bool = False

class DockerSandbox:
    def __init__(self, config: SandboxConfig = None):
        self.config = config or SandboxConfig()
        self.client = None
        self.container = None

    async def create(self) -> str:
        self.client = docker.from_env()
        container_config = {
            "image": self.config.image,
            "detach": True,
            "cpu_period": 100000,
            "cpu_quota": int(100000 * float(self.config.cpu_limit)),
            "mem_limit": self.config.memory_limit,
            "network_disabled": self.config.network_disabled,
            "read_only": True,
            "tty": True,
            "stdin_open": True,
        }
        loop = asyncio.get_event_loop()
        self.container = await loop.run_in_executor(
            None, lambda: self.client.containers.create(**container_config)
        )
        await loop.run_in_executor(None, self.container.start)
        return self.container.id

    async def execute(self, code: str, timeout: int = 300) -> dict:
        if not self.container:
            return {"error": "Sandbox not created"}
        escaped_code = code.replace("'", "'\"'\"'")
        exec_command = f"python3 -c '{escaped_code}'"
        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self.container.exec_run(exec_command)),
                timeout=timeout
            )
            return {"exit_code": result.exit_code, "output": result.output.decode("utf-8", errors="replace")}
        except asyncio.TimeoutError:
            return {"error": "Timeout", "exit_code": -1}
        except Exception as e:
            return {"error": str(e), "exit_code": -1}

    async def destroy(self):
        if self.container:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.container.stop)
                await loop.run_in_executor(None, self.container.remove)
            except Exception:
                pass
            self.container = None

    @staticmethod
    async def list_containers() -> list:
        try:
            client = docker.from_env()
            containers = client.containers.list(filters={"label": "agent_framework=true"})
            return [{"id": c.id, "name": c.name, "status": c.status} for c in containers]
        except Exception:
            return []


# === MCP ===
class MCPServer:
    def __init__(self, name: str):
        self.name = name
        self.tools = []

    def add_tool(self, name: str, description: str, input_schema: dict):
        self.tools.append({"name": name, "description": description, "input_schema": input_schema})

    def get_manifest(self) -> dict:
        return {"name": self.name, "tools": self.tools}


class MCPClient:
    def __init__(self):
        self.servers = {}

    async def connect(self, name: str, command: str, args: list = None, env: dict = None):
        import subprocess
        cmd = [command] + (args or [])
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env or {})
        self.servers[name] = process

    async def disconnect(self, name: str):
        if name in self.servers:
            self.servers[name].terminate()
            del self.servers[name]