"""
CLI Plugin Adapter — Subconscious Over-Agent System.

Bridge adapter for discovering, validating, and executing local CLI plugins
(e.g., android-cli, firebase-tools, git, uv, chrome-devtools) inside ExecutorSubOrchestrator.
Exposes CLI tools with safety boundaries, execution timeouts, and output truncation.
"""

import os
import sys
import shutil
import subprocess
from typing import Dict, List, Any, Optional

SUPPORTED_CLI_PLUGINS = {
    "android": {"cmd": "android", "description": "Android SDK & virtual device management CLI"},
    "firebase": {"cmd": "firebase", "description": "Firebase CLI tool for Hosting, Auth, Firestore"},
    "git": {"cmd": "git", "description": "Git source control management CLI"},
    "uv": {"cmd": "uv", "description": "Fast Python package and environment manager"},
    "docker": {"cmd": "docker", "description": "Container deployment and management CLI"}
}

class CLIPluginAdapter:
    """
    Adapter for registering and invoking CLI plugin commands safely.
    """
    def __init__(self):
        self.available_plugins: Dict[str, Dict[str, str]] = {}
        self._detect_plugins()

    def _detect_plugins(self):
        """Scans system PATH to discover installed CLI tools."""
        for name, spec in SUPPORTED_CLI_PLUGINS.items():
            cmd_path = shutil.which(spec["cmd"])
            if cmd_path:
                self.available_plugins[name] = {
                    "cmd": spec["cmd"],
                    "path": cmd_path,
                    "description": spec["description"]
                }

    def list_available_plugins(self) -> List[Dict[str, str]]:
        """Returns list of active CLI plugins detected on host system."""
        return [
            {"plugin": name, "path": info["path"], "description": info["description"]}
            for name, info in self.available_plugins.items()
        ]

    def execute_cli_plugin(self, plugin_name: str, args: List[str], timeout_s: float = 30.0, cwd: Optional[str] = None) -> Dict[str, Any]:
        """
        Executes a CLI plugin tool with timeout and output truncation boundaries.
        """
        if plugin_name not in self.available_plugins:
            return {
                "success": False,
                "output": f"CLI Plugin '{plugin_name}' is not installed on PATH.",
                "return_code": -1
            }

        cmd_entry = self.available_plugins[plugin_name]["cmd"]
        full_command = [cmd_entry] + args

        try:
            res = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=cwd or os.getcwd()
            )
            output = res.stdout if res.returncode == 0 else (res.stderr or res.stdout)
            
            # Truncate output to prevent prompt overflow
            if len(output) > 4000:
                output = output[:4000] + "\n... [CLI Plugin output truncated at 4000 chars]"

            return {
                "success": res.returncode == 0,
                "output": output.strip(),
                "return_code": res.returncode
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "output": f"CLI Plugin '{plugin_name}' execution timed out after {timeout_s} seconds.",
                "return_code": -124
            }
        except Exception as e:
            return {
                "success": False,
                "output": f"CLI Plugin execution error: {str(e)}",
                "return_code": -1
            }
