"""
Helix AGI — Crash Reporter & Unclean Shutdown Detector

Captures unhandled exceptions and system kills (like OOM), producing detailed,
masked post-mortem reports. Hooked into main process boot/shutdown.
"""

import os
import sys
import json
import time
import logging
import traceback
import subprocess
import threading
import platform
from typing import Optional, Dict, List, Any
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("helix.core.crash_reporter")

_BASE_DIR = Path(__file__).parent.parent
_SESSION_MARKER_PATH = _BASE_DIR / "logs" / "session_marker.json"
_CRASH_REPORTS_DIR = _BASE_DIR / "logs" / "crash_reports"

# Keys in config or env that should be masked in reports
SENSITIVE_KEYS = {
    "gemini_api_key",
    "anthropic_api_key",
    "openai_api_key",
    "telegram_token",
    "moltbook_api_key",
    "github_token",
    "telegram_bot_token",
    "api_key",
}


def mask_sensitive_dict(d: dict) -> dict:
    """Recursively mask sensitive keys in a dictionary."""
    masked = {}
    for k, v in d.items():
        if isinstance(v, dict):
            masked[k] = mask_sensitive_dict(v)
        elif isinstance(k, str) and any(sk in k.lower() for sk in SENSITIVE_KEYS):
            masked[k] = "•••••••• [MASKED]"
        else:
            masked[k] = v
    return masked


def get_system_stats() -> dict:
    """Collect basic system stats using psutil or fallback to platform APIs."""
    stats = {
        "os": platform.system(),
        "os_release": platform.release(),
        "python_version": sys.version,
        "cpu_count": os.cpu_count() or 1,
    }
    try:
        import psutil
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage('/')
        stats.update({
            "ram_total_gb": round(vm.total / (1024 ** 3), 2),
            "ram_available_gb": round(vm.available / (1024 ** 3), 2),
            "ram_percent": vm.percent,
            "swap_total_gb": round(swap.total / (1024 ** 3), 2),
            "swap_free_gb": round(swap.free / (1024 ** 3), 2),
            "disk_free_gb": round(disk.free / (1024 ** 3), 2),
        })
    except Exception:
        # Minimal fallbacks if psutil is not available
        stats["ram_info"] = "psutil unavailable"
    return stats


def get_last_log_lines(n: int = 50) -> str:
    """Retrieve the last N lines from helix.log."""
    log_path = _BASE_DIR / "logs" / "helix.log"
    if not log_path.exists():
        return "[helix.log not found]"
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            return "".join(lines[-n:])
    except Exception as e:
        return f"[Failed to read helix.log: {e}]"


def write_session_marker():
    """Create logs/session_marker.json indicating a running session."""
    try:
        _SESSION_MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
        config_data = {}
        config_path = _BASE_DIR / "config" / "config.json"
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    config_data = json.load(f)
            except Exception:
                pass

        marker = {
            "pid": os.getpid(),
            "status": "running",
            "start_time": datetime.now().isoformat(),
            "provider": config_data.get("llm_provider", "unknown"),
            "model": config_data.get("llm_model", "unknown"),
        }
        with open(_SESSION_MARKER_PATH, "w") as f:
            json.dump(marker, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to write session marker: {e}")


def clear_session_marker():
    """Update or remove the session marker to denote a clean shutdown."""
    try:
        if _SESSION_MARKER_PATH.exists():
            _SESSION_MARKER_PATH.unlink()
    except Exception as e:
        logger.warning(f"Failed to clear session marker: {e}")


def check_unclean_shutdown() -> Optional[dict]:
    """Scan for previous unclean shutdowns and compile a post-mortem if found.

    Runs on startup. If it detects a stale marker (status='running'),
    it runs a journalctl scan for OOM-kills/terminations and writes a report.
    Returns the report metadata if one was generated.
    """
    if not _SESSION_MARKER_PATH.exists():
        return None

    try:
        with open(_SESSION_MARKER_PATH, "r") as f:
            marker = json.load(f)
    except Exception:
        # Invalid file, just clean it up
        clear_session_marker()
        return None

    if marker.get("status") != "running":
        # clean shutdown
        clear_session_marker()
        return None

    pid = marker.get("pid")
    start_time_str = marker.get("start_time")
    
    # Check if process is still running (PID recycling could happen, but check baseline)
    if pid:
        try:
            # On Unix, sending signal 0 checks process existence
            os.kill(pid, 0)
            # Process is still running (maybe multiple main.py runs or developer testing)
            return None
        except OSError:
            pass

    # Process is not running and marker status was 'running' -> unclean shutdown!
    print(f"\n  ⚠  WARNING: Helix AGI did not shut down cleanly in the previous session (PID {pid}).")
    print("  Analyzing system logs for OOM-kills or termination signals...")

    # Query system user journal if possible
    journal_clues = []
    if start_time_str:
        try:
            # Parse ISO timestamp to journalctl format (YYYY-MM-DD HH:MM:SS)
            start_dt = datetime.fromisoformat(start_time_str)
            since_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
            # Run journalctl --user
            cmd = ["journalctl", "--user", "--since", since_str, "-n", "150", "--no-pager"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            if res.returncode == 0:
                lines = res.stdout.splitlines()
                # Filter for lines indicating kills, oom, or matching the PID
                for line in lines:
                    line_lower = line.lower()
                    if "oom" in line_lower or "kill" in line_lower or f"pid {pid}" in line_lower or str(pid) in line:
                        journal_clues.append(line)
        except Exception as je:
            journal_clues.append(f"[Failed to query journalctl: {je}]")

    # If journalctl had no user log entries or failed, try a quick grep on syslog as fallback
    if not journal_clues:
        syslog_path = Path("/var/log/syslog")
        if syslog_path.exists() and os.access(syslog_path, os.R_OK):
            try:
                # Basic search for oom-kill or our pid
                with open(syslog_path, "r", errors="ignore") as sf:
                    for line in sf:
                        if f"pid {pid}" in line or "oom-kill" in line.lower():
                            journal_clues.append(line.strip())
            except Exception:
                pass

    # Compile unclean shutdown report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _CRASH_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_base = f"unclean_shutdown_{timestamp}_{pid}"
    md_path = _CRASH_REPORTS_DIR / f"{report_base}.md"
    json_path = _CRASH_REPORTS_DIR / f"{report_base}.json"

    # Read configuration safely
    config_data = {}
    config_path = _BASE_DIR / "config" / "config.json"
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                config_data = json.load(f)
        except Exception:
            pass
    masked_config = mask_sensitive_dict(config_data)

    system_stats = get_system_stats()
    last_log = get_last_log_lines(50)

    # Markdown report
    md_content = f"""# Helix AGI Unclean Shutdown Report
Generated on: {datetime.now().isoformat()}
Previous PID: {pid}
Session Started: {start_time_str}

## Telemetry
The previous session terminated abruptly. This is often caused by:
1. Out-of-memory (OOM) killer terminating the Python process or extension host.
2. System shutdown or power loss.
3. Manual process termination via `kill -9`.

### System Clues (Journal / Syslog)
"""
    if journal_clues:
        md_content += "```\n" + "\n".join(journal_clues[-30:]) + "\n```\n"
    else:
        md_content += "_No matching OOM or kill signals found in user-space journal logs._\n"

    md_content += f"""
## System Information
- **OS**: {system_stats.get('os')} {system_stats.get('os_release')}
- **Python**: {system_stats.get('python_version')}
- **CPU Cores**: {system_stats.get('cpu_count')}
- **RAM Peak Total**: {system_stats.get('ram_total_gb', 'N/A')} GB
- **RAM Free at Report**: {system_stats.get('ram_available_gb', 'N/A')} GB
- **Swap Peak Total**: {system_stats.get('swap_total_gb', 'N/A')} GB
- **Swap Free at Report**: {system_stats.get('swap_free_gb', 'N/A')} GB
- **Disk Free**: {system_stats.get('disk_free_gb', 'N/A')} GB

## Masked Configuration
```json
{json.dumps(masked_config, indent=2)}
```

## Last 50 Lines of Logs
```
{last_log}
```
"""

    report_json = {
        "report_type": "unclean_shutdown",
        "timestamp": datetime.now().isoformat(),
        "pid": pid,
        "session_started": start_time_str,
        "clues": journal_clues,
        "system_stats": system_stats,
        "config": masked_config,
    }

    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_json, f, indent=2)
        print(f"  ✓ Compiled post-mortem report: logs/crash_reports/{report_base}.md")
    except Exception as e:
        logger.error(f"Failed to write unclean shutdown report: {e}")

    # Remove the stale session marker now that we processed it
    clear_session_marker()
    return report_json


def generate_crash_report(exc_type, exc_value, exc_traceback, is_thread=False, thread_name=None):
    """Compile and write a full crash report for an unhandled exception."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pid = os.getpid()
    
    _CRASH_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_base = f"crash_report_{timestamp}_{pid}"
    md_path = _CRASH_REPORTS_DIR / f"{report_base}.md"
    json_path = _CRASH_REPORTS_DIR / f"{report_base}.json"

    # Get traceback
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
    tb_str = "".join(tb_lines)

    # Get system stats
    system_stats = get_system_stats()

    # Get last logs
    last_log = get_last_log_lines(50)

    # Read config
    config_data = {}
    config_path = _BASE_DIR / "config" / "config.json"
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                config_data = json.load(f)
        except Exception:
            pass
    masked_config = mask_sensitive_dict(config_data)

    # Get list of active threads
    active_threads = []
    for t in threading.enumerate():
        active_threads.append({
            "name": t.name,
            "id": t.ident,
            "daemon": t.daemon,
            "alive": t.is_alive(),
        })

    md_content = f"""# Helix AGI Agent Crash Report
Generated on: {datetime.now().isoformat()}
PID: {pid}
Thread: {thread_name if thread_name else 'MainThread'} (Is Thread: {is_thread})

## Exception Details
**{exc_type.__name__ if exc_type else 'UnknownException'}**: {exc_value}

### Traceback
```python
{tb_str}
```

## System Information
- **OS**: {system_stats.get('os')} {system_stats.get('os_release')}
- **Python**: {system_stats.get('python_version')}
- **CPU Cores**: {system_stats.get('cpu_count')}
- **RAM Total**: {system_stats.get('ram_total_gb', 'N/A')} GB
- **RAM Free**: {system_stats.get('ram_available_gb', 'N/A')} GB
- **Swap Total**: {system_stats.get('swap_total_gb', 'N/A')} GB
- **Swap Free**: {system_stats.get('swap_free_gb', 'N/A')} GB
- **Disk Free**: {system_stats.get('disk_free_gb', 'N/A')} GB

## Masked Configuration
```json
{json.dumps(masked_config, indent=2)}
```

## Active Threads
"""
    for t in active_threads:
        md_content += f"- **{t['name']}** (ID: {t['id']}, Daemon: {t['daemon']}, Alive: {t['alive']})\n"

    md_content += f"""
## Last 50 Lines of Logs
```
{last_log}
```
"""

    report_json = {
        "report_type": "exception",
        "timestamp": datetime.now().isoformat(),
        "pid": pid,
        "thread": thread_name,
        "is_thread": is_thread,
        "exception": {
            "type": exc_type.__name__ if exc_type else "None",
            "message": str(exc_value),
            "traceback": tb_str,
        },
        "system_stats": system_stats,
        "config": masked_config,
        "threads": active_threads,
    }

    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_json, f, indent=2)
        
        # Output print directly to console for user visibility
        print(f"\n" + "="*80)
        print("  🚨 HELIX AGI HAS CRASHED!")
        print("="*80)
        print(f"  Unhandled Exception: {exc_type.__name__ if exc_type else 'Unknown'}: {exc_value}")
        print(f"  A detailed crash report has been saved to:")
        print(f"    - Markdown: logs/crash_reports/{report_base}.md")
        print(f"    - JSON:     logs/crash_reports/{report_base}.json")
        print("="*80 + "\n")
    except Exception as e:
        # Avoid looping if we fail to write
        print(f"Failed to write crash report files: {e}", file=sys.stderr)


def handle_exception(exc_type, exc_value, exc_traceback):
    """Unhandled exception handler for sys.excepthook."""
    if issubclass(exc_type, KeyboardInterrupt):
        # Graceful interrupt, clear marker and standard exit
        clear_session_marker()
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    # Log it
    logger.critical("Unhandled exception in main thread", exc_info=(exc_type, exc_value, exc_traceback))
    
    # Generate report
    generate_crash_report(exc_type, exc_value, exc_traceback, is_thread=False)

    # Clean up marker and call default hook
    clear_session_marker()
    sys.__excepthook__(exc_type, exc_value, exc_traceback)


def handle_thread_exception(args):
    """Unhandled exception handler for threading.excepthook."""
    exc_type = args.exc_type
    exc_value = args.exc_value
    exc_traceback = args.exc_traceback
    thread = args.thread

    if issubclass(exc_type, KeyboardInterrupt):
        return

    logger.critical(
        f"Unhandled exception in thread {thread.name if thread else 'unknown'}",
        exc_info=(exc_type, exc_value, exc_traceback)
    )

    generate_crash_report(
        exc_type, exc_value, exc_traceback,
        is_thread=True, thread_name=thread.name if thread else "unknown"
    )
    # Thread exceptions don't terminate the process automatically,
    # but we clear the marker and let system handle it
    clear_session_marker()


def setup_crash_reporter():
    """Register crash reporter hooks and write session marker."""
    sys.excepthook = handle_exception
    if hasattr(threading, "excepthook"):
        threading.excepthook = handle_thread_exception
    
    write_session_marker()
