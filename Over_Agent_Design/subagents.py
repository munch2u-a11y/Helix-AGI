"""
Slim Orchestrator & Sub-Orchestrator Tool-Group Passes.
Main Orchestrator remains ultra-slim.
ResearcherSubOrchestrator utilizes HelixMRAGAdapter for multi-head mRAG recall over Helix local memories.
"""

import os
import glob
import subprocess
import urllib.request
import urllib.parse
import json
import re
from typing import Dict, Any
from llm_backend import LLMBackend
from mrag_adapter import HelixMRAGAdapter

IDENTITY_FILE_PATH = "/home/nemo/Over_Agent_Design/identity.md"

def load_shared_identity() -> str:
    if os.path.exists(IDENTITY_FILE_PATH):
        with open(IDENTITY_FILE_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    return "I am Helix, a continuous digital mind operating through focused cognitive windows."


class SpeakerFocus:
    """Vocal Cognitive Mode: Express dialogue directly to the user."""
    def __init__(self, backend: LLMBackend):
        self.backend = backend

    def run(self, task_instruction: str, user_context: str) -> str:
        identity = load_shared_identity()
        system_prompt = (
            f"{identity}\n\n"
            "COGNITIVE MODE: Vocal / Speaking\n"
            "I am speaking directly to the user in a natural, clear, and helpful voice."
        )
        prompt = (
            f"USER CONTEXT:\n{user_context}\n\n"
            f"MY INTERNAL DIRECTIVE:\n{task_instruction}\n\n"
            "My spoken response to the user:"
        )
        return self.backend.generate(prompt=prompt, system_prompt=system_prompt, temperature=0.7)


class ResearcherSubOrchestrator:
    """
    Research Sub-Orchestrator Pass.
    Utilizes mRAG multi-head memory recall over Helix local memory stores (/home/nemo/Helix/data),
    workspace scan, and web search.
    """
    def __init__(self, backend: LLMBackend):
        self.backend = backend
        self.mrag_adapter = HelixMRAGAdapter()

    def run(self, query: str, search_path: str = "/home/nemo/Over_Agent_Design") -> str:
        identity = load_shared_identity()
        
        # 1. Execute Multi-Head mRAG Preconscious Recall
        mrag_context = self.mrag_adapter.retrieve_mrag_context(query)
        
        # 2. Local Workspace File Scan
        workspace_scan = self._scan_workspace(search_path)
        
        # 3. Dynamic Tool Selection Pass
        sub_system = (
            f"{identity}\n\n"
            "COGNITIVE DOMAIN: Research Sub-Orchestrator (mRAG Enabled)\n"
            "Select the best tool pass to fulfill this research request.\n"
            "TOOL OPTIONS:\n"
            "1. 'mrag': Multi-head mRAG search over Helix memory stores and belief files.\n"
            "2. 'workspace': Search local workspace files.\n"
            "3. 'web': Search live online web pages.\n"
            "Output JSON: {\"tool\": \"mrag\"|\"workspace\"|\"web\", \"target\": \"query\"}"
        )
        sub_prompt = f"RESEARCH TASK: {query}\n\nSelect tool and execute:"
        selection = self.backend.generate(prompt=sub_prompt, system_prompt=sub_system, temperature=0.1)
        
        selected_tool = "mrag"
        if "web" in selection.lower() or "online" in query.lower() or "news" in query.lower():
            selected_tool = "web"
        elif "workspace" in selection.lower() or "file" in query.lower():
            selected_tool = "workspace"
            
        if selected_tool == "web":
            res = self._fetch_web_results(query)
            tool_name = "Web Search"
        elif selected_tool == "workspace":
            res = workspace_scan
            tool_name = "Workspace Scanner"
        else:
            res = mrag_context
            tool_name = "mRAG Multi-Head Memory Store"
            
        system_prompt = (
            f"{identity}\n\n"
            f"COGNITIVE MODE: Research Synthesizer ({tool_name})\n"
            "Synthesize key findings into a concise observation for my main stream."
        )
        prompt = f"RESEARCH QUERY: {query}\nmRAG & RECALLED CONTEXT:\n{mrag_context}\n\nTOOL RESULTS ({tool_name}):\n{res}\n\nMy concise observation:"
        return self.backend.generate(prompt=prompt, system_prompt=system_prompt, temperature=0.2)

    def _scan_workspace(self, search_path: str) -> str:
        results = []
        if os.path.exists(search_path):
            files = glob.glob(f"{search_path}/**/*", recursive=True)
            results = [f for f in files if os.path.isfile(f)]
        return "\n".join(results[:15]) if results else "No local files found."

    def _fetch_web_results(self, query: str) -> str:
        try:
            encoded_query = urllib.parse.quote_plus(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', html, re.DOTALL)
            clean_snippets = [re.sub(r'<[^>]+>', '', s).strip() for s in snippets[:4]]
            return "\n".join(f"- {s}" for s in clean_snippets) if clean_snippets else f"Web search completed for '{query}'."
        except Exception as e:
            return f"Web search note: {e}"


class ExecutorSubOrchestrator:
    """
    Execution Sub-Orchestrator Pass.
    Dynamically routes technical tasks to specific tools (Code Review vs Shell Command vs Vision).
    """
    def __init__(self, backend: LLMBackend):
        self.backend = backend

    def run(self, task_description: str) -> str:
        identity = load_shared_identity()
        
        sub_system = (
            f"{identity}\n\n"
            "COGNITIVE DOMAIN: Execution Sub-Orchestrator\n"
            "Select the specific tool for this execution task.\n"
            "TOOL OPTIONS:\n"
            "1. 'code': Review code or technical specs.\n"
            "2. 'shell': Execute bash CLI command.\n"
            "3. 'vision': Inspect desktop display screenshot.\n"
            "Output JSON: {\"tool\": \"code\"|\"shell\"|\"vision\", \"target\": \"details\"}"
        )
        selection = self.backend.generate(prompt=task_description, system_prompt=sub_system, temperature=0.1)
        
        if "shell" in selection.lower() or "command" in task_description.lower() or "open" in task_description.lower():
            res = self._run_shell(task_description)
            tool_name = "Shell Exec"
        elif "vision" in selection.lower() or "screen" in task_description.lower() or "desktop" in task_description.lower():
            res = self._run_screen_capture()
            tool_name = "Screen Vision"
        else:
            res = f"Technical code task: {task_description}"
            tool_name = "Code Engine"
            
        system_prompt = (
            f"{identity}\n\n"
            f"COGNITIVE MODE: Execution Result Synthesizer ({tool_name})\n"
            "Synthesize execution status into a concise observation for my main stream."
        )
        prompt = f"TASK: {task_description}\nEXECUTION RESULT ({tool_name}):\n{res}\n\nMy concise observation:"
        return self.backend.generate(prompt=prompt, system_prompt=system_prompt, temperature=0.2)

    def _run_shell(self, cmd: str) -> str:
        try:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            return res.stdout.strip() or res.stderr.strip() or "Command completed cleanly."
        except Exception as e:
            return f"Shell execution note: {e}"

    def _run_screen_capture(self) -> str:
        try:
            target = "/home/nemo/Over_Agent_Design/current_screen.xwd"
            res = subprocess.run(f"xwd -root -out {target}", shell=True, capture_output=True, text=True, timeout=5)
            return f"Captured desktop screen to {target} ({os.path.getsize(target)} bytes)." if os.path.exists(target) else "Screen capture attempted."
        except Exception as e:
            return f"Vision capture note: {e}"
