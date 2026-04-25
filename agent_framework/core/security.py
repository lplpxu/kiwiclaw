"""Dangerous Command Detection and Security

Comprehensive pattern-based detection for dangerous commands.
Inspired by hermes-agent/tools/approval.py

Features:
- 60+ regex patterns for dangerous commands
- Per-session and permanent allowlists
- Smart approval via auxiliary LLM
- Thread-safe approval state
"""

import contextvars
import logging
import os
import re
import threading
import unicodedata
from typing import Optional, Tuple, Set

logger = logging.getLogger(__name__)

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE7] [Security] {msg}")


# ============================================================================
# Dangerous command patterns
# ============================================================================

# Sensitive write targets that should trigger approval even when referenced
# via shell expansions like $HOME or $HERMES_HOME.
_SSH_SENSITIVE_PATH = r'(?:~|\$home|\$\{home\})/\.ssh(?:/|$)'
_HERMES_ENV_PATH = (
    r'(?:~\/\.hermes/|'
    r'(?:\$home|\$\{home\})/\.hermes/|'
    r'(?:\$hermes_home|\$\{hermes_home\})/)'
    r'\.env\b'
)
_SENSITIVE_WRITE_TARGET = (
    r'(?:/etc/|/dev/sd|'
    rf'{_SSH_SENSITIVE_PATH}|'
    rf'{_HERMES_ENV_PATH})'
)

DANGEROUS_PATTERNS = [
    # File deletion patterns
    (r'\brm\s+(-[^\s]*\s+)*/', "delete in root path"),
    (r'\brm\s+-[^\s]*r', "recursive delete"),
    (r'\brm\s+--recursive\b', "recursive delete (long flag)"),

    # Permission modification patterns
    (r'\bchmod\s+(-[^\s]*\s+)*(777|666|o\+[rwx]*w|a\+[rwx]*w)\b', "world/other-writable permissions"),
    (r'\bchmod\s+--recursive\b.*(777|666|o\+[rwx]*w|a\+[rwx]*w)', "recursive world/other-writable (long flag)"),
    (r'\bchown\s+(-[^\s]*)?R\s+root', "recursive chown to root"),
    (r'\bchown\s+--recursive\b.*root', "recursive chown to root (long flag)"),

    # Filesystem destruction
    (r'\bmkfs\b', "format filesystem"),
    (r'\bdd\s+.*if=', "disk copy"),
    (r'>\s*/dev/sd', "write to block device"),

    # SQL destruction
    (r'\bDROP\s+(TABLE|DATABASE)\b', "SQL DROP"),
    (r'\bDELETE\s+FROM\b(?!.*\bWHERE\b)', "SQL DELETE without WHERE"),
    (r'\bTRUNCATE\s+(TABLE)?\s*\w', "SQL TRUNCATE"),

    # System config overwrite
    (r'>\s*/etc/', "overwrite system config"),

    # Service management
    (r'\bsystemctl\s+(-[^\s]+\s+)*(stop|restart|disable|mask)\b', "stop/restart system service"),

    # Process killing
    (r'\bkill\s+-9\s+-1\b', "kill all processes"),
    (r'\bpkill\s+-9\b', "force kill processes"),

    # Fork bomb
    (r':\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:', "fork bomb"),

    # Shell execution via -c flag
    (r'\b(bash|sh|zsh|ksh)\s+-[^\s]*c(\s+|$)', "shell command via -c/-lc flag"),

    # Script execution via -e/-c flag
    (r'\b(python[23]?|perl|ruby|node)\s+-[ec]\s+', "script execution via -e/-c flag"),

    # Pipe remote content to shell
    (r'\b(curl|wget)\b.*\|\s*(ba)?sh\b', "pipe remote content to shell"),

    # Execute remote script via process substitution
    (r'\b(bash|sh|zsh|ksh)\s+<\s*<?\s*\(\s*(curl|wget)\b', "execute remote script via process substitution"),

    # Tee to sensitive paths
    (rf'\btee\b.*["\']?{_SENSITIVE_WRITE_TARGET}', "overwrite system file via tee"),
    (rf'>>?\s*["\']?{_SENSITIVE_WRITE_TARGET}', "overwrite system file via redirection"),

    # xargs with rm
    (r'\bxargs\s+.*\brm\b', "xargs with rm"),
    (r'\bfind\b.*-exec\s+(/\S*/)?rm\b', "find -exec rm"),
    (r'\bfind\b.*-delete\b', "find -delete"),

    # Gateway lifecycle protection
    (r'\bhermes\s+gateway\s+(stop|restart)\b', "stop/restart hermes gateway (kills running agents)"),
    (r'\bhermes\s+update\b', "hermes update (restarts gateway, kills running agents)"),

    # Start gateway outside systemd
    (r'gateway\s+run\b.*(&\s*$|&\s*;|\bdisown\b|\bsetsid\b)', "start gateway outside systemd"),
    (r'\bnohup\b.*gateway\s+run\b', "start gateway outside systemd"),

    # Self-termination protection
    (r'\b(pkill|killall)\b.*\b(hermes|gateway|cli\.py)\b', "kill hermes/gateway process (self-termination)"),
    (r'\bkill\b.*\$\(\s*pgrep\b', "kill process via pgrep expansion (self-termination)"),
    (r'\bkill\b.*`\s*pgrep\b', "kill process via backtick pgrep expansion (self-termination)"),

    # File copy/move to sensitive paths
    (r'\b(cp|mv|install)\b.*\s/etc/', "copy/move file into /etc/"),

    # Sed in-place to system config
    (r'\bsed\s+-[^\s]*i.*\s/etc/', "in-place edit of system config"),
    (r'\bsed\s+--in-place\b.*\s/etc/', "in-place edit of system config (long flag)"),

    # Script execution via heredoc
    (r'\b(python[23]?|perl|ruby|node)\s+<<', "script execution via heredoc"),

    # Git destructive operations
    (r'\bgit\s+reset\s+--hard\b', "git reset --hard (destroys uncommitted changes)"),
    (r'\bgit\s+push\b.*--force\b', "git force push (rewrites remote history)"),
    (r'\bgit\s+push\b.*-f\b', "git force push short flag (rewrites remote history)"),
    (r'\bgit\s+clean\s+-[^\s]*f', "git clean with force (deletes untracked files)"),
    (r'\bgit\s+branch\s+-D\b', "git branch force delete"),

    # chmod +x followed by execution
    (r'\bchmod\s+\+x\b.*[;&|]+\s*\./', "chmod +x followed by immediate execution"),

    # Windows-specific dangerous patterns
    (r'\bformat\b.*/[es]:', "format filesystem on Windows"),
    (r'\brmdir\b.*/s\b', "recursive directory removal on Windows"),
    (r'\bdel\b.*/f\b.*/s\b', "force delete files on Windows"),
    (r'\bcipher\b.*/d\b', "cipher wipe on Windows"),
    (r'\bnet\s+stop\b', "stop Windows service"),
    (r'\bnet\s+user\b.*/delete\b', "delete Windows user"),
    (r'\bdisable\b.*-computer\b', "disable computer via WMIC"),
]

# Pattern key aliases for backwards compatibility
_PATTERN_KEY_ALIASES: dict[str, set[str]] = {}
for _pattern, _description in DANGEROUS_PATTERNS:
    _canonical_key = _description
    _PATTERN_KEY_ALIASES.setdefault(_canonical_key, set()).add(_canonical_key)


def _normalize_command_for_detection(command: str) -> str:
    """Normalize a command string before dangerous-pattern matching.

    Strips ANSI escape sequences, null bytes, and normalizes Unicode
    fullwidth characters so that obfuscation techniques cannot bypass
    the pattern-based detection.
    """
    # Strip ANSI escape sequences (CSI, OSC, DCS, 8-bit C1, etc.)
    command = _strip_ansi(command)
    # Strip null bytes
    command = command.replace('\x00', '')
    # Normalize Unicode (fullwidth Latin, halfwidth Katakana, etc.)
    command = unicodedata.normalize('NFKC', command)
    return command


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    # ANSI escape sequences pattern
    ansi_pattern = r'\x1b\[[0-9;]*[a-zA-Z]|\x1b[()][AB012]|\x1b\][^\x07]*\x07|\x1b'
    return re.sub(ansi_pattern, '', text)


def detect_dangerous_command(command: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """Check if a command matches any dangerous patterns.

    Returns:
        (is_dangerous, pattern_key, description) or (False, None, None)
    """
    command_lower = _normalize_command_for_detection(command).lower()
    for pattern, description in DANGEROUS_PATTERNS:
        try:
            if re.search(pattern, command_lower, re.IGNORECASE | re.DOTALL):
                pattern_key = description
                return (True, pattern_key, description)
        except re.error:
            continue
    return (False, None, None)


# ============================================================================
# Per-session approval state (thread-safe)
# ============================================================================

_lock = threading.Lock()
_session_approved: dict[str, set] = {}
_session_yolo: set[str] = set()
_permanent_approved: set = str()


def approve_session(session_key: str, pattern_key: str) -> None:
    """Approve a pattern for this session only."""
    with _lock:
        _session_approved.setdefault(session_key, set()).add(pattern_key)


def enable_session_yolo(session_key: str) -> None:
    """Enable YOLO bypass for a single session key."""
    if not session_key:
        return
    with _lock:
        _session_yolo.add(session_key)


def disable_session_yolo(session_key: str) -> None:
    """Disable YOLO bypass for a single session key."""
    if not session_key:
        return
    with _lock:
        _session_yolo.discard(session_key)


def is_session_yolo_enabled(session_key: str) -> bool:
    """Return True when YOLO bypass is enabled for a specific session."""
    if not session_key:
        return False
    with _lock:
        return session_key in _session_yolo


def is_pattern_approved(session_key: str, pattern_key: str) -> bool:
    """Check if a pattern is approved (session-scoped or permanent)."""
    aliases = _PATTERN_KEY_ALIASES.get(pattern_key, {pattern_key})
    with _lock:
        if any(alias in _permanent_approved for alias in aliases):
            return True
        session_approvals = _session_approved.get(session_key, set())
        return any(alias in session_approvals for alias in aliases)


def clear_session(session_key: str) -> None:
    """Remove all approval and yolo state for a given session."""
    if not session_key:
        return
    with _lock:
        _session_approved.pop(session_key, None)
        _session_yolo.discard(session_key)


# ============================================================================
# Approval modes
# ============================================================================

class ApprovalMode:
    """Approval mode constants."""
    OFF = "off"           # No approval required
    MANUAL = "manual"     # Always prompt user
    SMART = "smart"       # Use LLM for uncertain cases
    AUTO_APPROVE = "auto_approve"  # Auto-approve except clear dangers


# ============================================================================
# Smart approval via LLM
# ============================================================================

def _smart_approve(command: str, description: str) -> str:
    """Use the auxiliary LLM to assess risk and decide approval.

    Returns 'approve' if the LLM determines the command is safe,
    'deny' if genuinely dangerous, or 'escalate' if uncertain.

    Inspired by OpenAI Codex's Smart Approvals guardian subagent.
    """
    try:
        from ._tools import run_judge

        prompt = f"""You are a security reviewer for an AI coding agent. A terminal command was flagged by pattern matching as potentially dangerous.

Command: {command}
Flagged reason: {description}

Assess the ACTUAL risk of this command. Many flagged commands are false positives — for example, `python -c "print('hello')"` is flagged as "script execution via -c flag" but is completely harmless.

Rules:
- APPROVE if the command is clearly safe (benign script execution, safe file operations, development tools, package installs, git operations, etc.)
- DENY if the command could genuinely damage the system (recursive delete of important paths, overwriting system files, fork bombs, wiping disks, dropping databases, etc.)
- ESCALATE if you're uncertain

Respond with exactly one word: APPROVE, DENY, or ESCALATE"""

        # Use a simple LLM call for approval assessment
        auth_token = os.getenv("ANTHROPIC_AUTH_TOKEN", "")
        if not auth_token:
            return "escalate"

        import anthropic
        client = anthropic.Anthropic(api_key=auth_token)

        response = client.messages.create(
            model="MiniMax-M2.7",
            max_tokens=16,
            temperature=0,
            messages=[{"role": "user", "content": prompt}]
        )

        answer = (response.content[0].text or "").strip().upper()

        if "APPROVE" in answer:
            return "approve"
        elif "DENY" in answer:
            return "deny"
        else:
            return "escalate"

    except Exception as e:
        _debug(f"Smart approval LLM call failed: {e}")
        return "escalate"


# ============================================================================
# Main security check function
# ============================================================================

def check_command_security(
    command: str,
    approval_mode: str = ApprovalMode.MANUAL,
    session_key: str = "default",
    skip_containers: bool = True,
    env_type: str = "local"
) -> dict:
    """Check if a command is dangerous and handle approval.

    This is the main entry point for checking commands before execution.

    Args:
        command: The shell command to check.
        approval_mode: Approval mode (off, manual, smart, auto_approve).
        session_key: Session identifier for per-session approvals.
        skip_containers: Skip approval for container environments.
        env_type: Terminal backend type (local, ssh, docker, etc.).

    Returns:
        dict with keys:
            - approved: bool
            - message: str or None
            - pattern_key: str or None (if dangerous)
            - description: str or None
    """
    # Skip approval for container environments
    if skip_containers and env_type in ("docker", "singularity", "modal", "daytona"):
        return {"approved": True, "message": None}

    # Check YOLO mode
    if os.getenv("AGENT_YOLO_MODE") or is_session_yolo_enabled(session_key):
        return {"approved": True, "message": None}

    # Check if command is dangerous
    is_dangerous, pattern_key, description = detect_dangerous_command(command)

    if not is_dangerous:
        # Auto-approve non-dangerous commands
        if approval_mode == ApprovalMode.AUTO_APPROVE:
            return {"approved": True, "message": None}
        # In other modes, non-dangerous commands pass detection
        return {"approved": True, "message": None}

    # Command is dangerous - check if already approved
    if is_pattern_approved(session_key, pattern_key):
        return {"approved": True, "message": None}

    # Handle different approval modes
    if approval_mode == ApprovalMode.OFF:
        # In OFF mode, only clear dangers are blocked
        # Check if this is a very dangerous command
        very_dangerous = ["delete in root path", "format filesystem", "disk copy",
                         "fork bomb", "kill all processes", "SQL DROP"]
        if pattern_key in very_dangerous:
            return {
                "approved": False,
                "message": f"BLOCKED: Command flagged as very dangerous ({description}). "
                          "Find an alternative approach.",
                "pattern_key": pattern_key,
                "description": description,
            }
        return {"approved": True, "message": None}

    elif approval_mode == ApprovalMode.AUTO_APPROVE:
        # Auto-approve except for very dangerous commands
        very_dangerous = ["delete in root path", "format filesystem", "disk copy",
                         "fork bomb", "kill all processes", "SQL DROP",
                         "overwrite system config", "git reset --hard"]
        if pattern_key in very_dangerous:
            return {
                "approved": False,
                "message": f"BLOCKED: Very dangerous command ({description}). "
                          "Use a safer alternative or explicitly approve.",
                "pattern_key": pattern_key,
                "description": description,
            }
        return {"approved": True, "message": None}

    elif approval_mode == ApprovalMode.SMART:
        # Use LLM to assess uncertain cases
        verdict = _smart_approve(command, description)
        if verdict == "approve":
            # Auto-approve and grant session-level approval
            approve_session(session_key, pattern_key)
            _debug(f"Smart approval: auto-approved '{command[:60]}' ({description})")
            return {"approved": True, "message": None,
                    "smart_approved": True, "description": description}
        elif verdict == "deny":
            return {
                "approved": False,
                "message": f"BLOCKED by smart approval: {description}. "
                          "The command was assessed as genuinely dangerous. Do NOT retry.",
                "smart_denied": True,
                "pattern_key": pattern_key,
                "description": description,
            }
        # verdict == "escalate" → fall through to manual prompt

    # MANUAL mode or SMART escalated - require approval
    return {
        "approved": False,
        "status": "approval_required",
        "pattern_key": pattern_key,
        "command": command,
        "description": description,
        "message": (
            f"⚠️ This command is potentially dangerous ({description}). "
            f"Approval required.\n\n**Command:**\n```\n{command}\n```"
        ),
    }


# ============================================================================
# Integration with PermissionEnforcer
# ============================================================================

def check_bash_security(command: str, session_key: str = "default") -> Tuple[bool, str]:
    """Check bash command security and return (approved, message).

    This is the integration point with PermissionEnforcer.

    Returns:
        (True, "") if approved
        (False, error_message) if blocked
    """
    # Check environment variable for approval mode
    approval_mode = os.getenv("AGENT_APPROVAL_MODE", ApprovalMode.MANUAL)

    result = check_command_security(
        command=command,
        approval_mode=approval_mode,
        session_key=session_key
    )

    if result["approved"]:
        return (True, "")
    else:
        return (False, result.get("message", "Command blocked by security policy"))


# Load permanent allowlist from config on module import
def _load_permanent_allowlist() -> set:
    """Load permanently allowed command patterns from config."""
    try:
        # Try to load from config
        from ..config.settings import settings
        patterns = set(getattr(settings, 'command_allowlist', []) or [])
        if patterns:
            with _lock:
                global _permanent_approved
                _permanent_approved = patterns
        return patterns
    except Exception:
        return set()


_load_permanent_allowlist()