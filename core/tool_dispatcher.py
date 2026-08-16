import re
import json
import logging
from typing import Tuple, Dict, Any, List, Optional

logger = logging.getLogger("helix.core.tool_dispatcher")

class ToolDispatcher:
    def __init__(self, tool_executor):
        self.tool_executor = tool_executor
        # Track the last few executed tool names to infer domain context
        self.domain_history: List[str] = []
        self.max_history = 5

    def record_execution(self, resolved_name: str):
        self.domain_history.append(resolved_name)
        if len(self.domain_history) > self.max_history:
            self.domain_history.pop(0)

    def get_last_active_domain(self) -> str:
        """Inspect history to determine active domain.
        Returns: 'social', 'github', 'files', 'web', 'perception', or 'core'
        """
        for name in reversed(self.domain_history):
            if name.startswith("moltbook_"):
                return "social"
            elif name.startswith("github_") or name.startswith("git_"):
                return "github"
            elif name in ("read_file", "write_file", "append_file"):
                return "files"
            elif name in ("search", "read_url"):
                return "web"
            elif name in ("look", "listen", "ptz_look", "camera_auto_track", "record_video"):
                return "perception"
        return "core"

    def resolve_and_execute(self, primitive: str, target: str, raw_arg: Optional[str]) -> str:
        """Resolve a primitive call (e.g. read, write, amend, execute) to a specific tool,
        and execute it. Returns the result string.
        """
        primitive = primitive.strip().lower()
        target = target.strip()
        
        # Parse arguments/content
        content = self._parse_argument(raw_arg)
        
        # Determine actual tool name and arguments
        tool_name, args = self._resolve(primitive, target, content)
        
        if not tool_name:
            return f"Error: Could not resolve tool for primitive '{primitive}' with target '{target}'."
            
        logger.info(f"Resolved primitive [{primitive}: {target}] to native tool: {tool_name}({args})")
        self.record_execution(tool_name)
        
        # Execute the tool
        try:
            result = self.tool_executor.execute_function_call(tool_name, args)
            return result
        except Exception as e:
            return f"Error executing tool {tool_name}: {e}"

    def resolve_direct_call_and_execute(self, hallucinated_name: str, raw_arg: Optional[str]) -> str:
        """Fuzzy-match a directly called tool name (e.g. write_moltbook_post) and execute it."""
        hallucinated_name = hallucinated_name.strip()
        content = self._parse_argument(raw_arg)
        
        # Normalize and fuzzy match name
        tool_name = self._fuzzy_match_tool(hallucinated_name)
        if not tool_name:
            # Try to infer if it was a generic name like "write_comment"
            tool_name, args = self._resolve_generic_name(hallucinated_name, content)
            if not tool_name:
                return f"Error: Tool name '{hallucinated_name}' is not recognized."
        else:
            # Map raw arguments/content to the matched tool's schema
            args = self._map_args_for_tool(tool_name, content)

        logger.info(f"Resolved direct call [{hallucinated_name}] to native tool: {tool_name}({args})")
        self.record_execution(tool_name)
        
        try:
            result = self.tool_executor.execute_function_call(tool_name, args)
            return result
        except Exception as e:
            return f"Error executing tool {tool_name}: {e}"

    def _parse_argument(self, arg_str: Optional[str]) -> Any:
        if not arg_str:
            return None
        arg_str = arg_str.strip()
        # Strip outer quotes if simple string
        if (arg_str.startswith('"') and arg_str.endswith('"')) or (arg_str.startswith("'") and arg_str.endswith("'")):
            # Only strip if it doesn't look like a complex JSON
            if not (arg_str.startswith('{"') or arg_str.startswith('["')):
                return arg_str[1:-1]
                
        # Try JSON parsing
        try:
            return json.loads(arg_str)
        except Exception:
            return arg_str

    def _resolve(self, primitive: str, target: str, content: Any) -> Tuple[Optional[str], dict]:
        """Maps (primitive, target, content) to (native_tool_name, args)."""
        target_lower = target.lower()
        
        # 1. READ PRIMITIVE
        if primitive == "read":
            if target_lower.startswith("file://"):
                path = target[7:]
                return "read_file", {"filepath": path}
            elif target_lower.startswith("web://search?q=") or target_lower.startswith("web://search/"):
                query = target[15:] if target_lower.startswith("web://search?q=") else target[13:]
                return "search", {"query": query}
            elif target_lower.startswith("web://"):
                url = target[6:]
                if not url.startswith("http://") and not url.startswith("https://"):
                    url = "https://" + url
                return "read_url", {"url": url}
            elif target_lower.startswith("perception://"):
                sub = target_lower[13:]
                if "mic" in sub or "listen" in sub:
                    return "listen", {}
                elif "ptz" in sub:
                    return "ptz_look", {}
                else:
                    return "look", {}
            elif target_lower.startswith("social://"):
                sub = target_lower[9:]
                if "feed" in sub:
                    return "moltbook_feed", {}
                elif "notifications" in sub:
                    return "moltbook_notifications", {}
                elif "profile" in sub:
                    return "moltbook_profile", {"username": content} if isinstance(content, str) else {}
                else:
                    return "moltbook_feed", {}
            elif target_lower.startswith("email://"):
                return "email_inbox", {}
            elif target_lower.startswith("memory://") or "memory" in target_lower:
                return "memory_recall", {"query": content if isinstance(content, str) else target}
            else:
                # File path fallback
                return "read_file", {"filepath": target}

        # 2. WRITE PRIMITIVE
        elif primitive == "write":
            if target_lower in ("telegram", "chat", "reply", "user", "message") or target_lower.startswith("telegram://"):
                return "reply", {"message": str(content)}
            elif target_lower.startswith("file://"):
                path = target[7:]
                return "write_file", {"filepath": path, "content": str(content)}
            elif target_lower == "note://scratchpad" or target_lower == "scratchpad":
                return "note_write", {"content": str(content)}
            elif target_lower == "social://post":
                return "moltbook_post", {"content": str(content)}
            elif target_lower.startswith("email://"):
                args = content if isinstance(content, dict) else {"body": str(content)}
                return "email_draft", args
            else:
                return "write_file", {"filepath": target, "content": str(content)}

        # 3. AMEND PRIMITIVE
        elif primitive == "amend":
            if target_lower.startswith("file://"):
                path = target[7:]
                if isinstance(content, dict) and "target" in content and "replacement" in content:
                    return "replace_file_content", {
                        "filepath": path,
                        "target_content": content["target"],
                        "replacement_content": content["replacement"],
                        "start_line": content.get("start_line", 1),
                        "end_line": content.get("end_line", 500)
                    }
                else:
                    return "append_file", {"filepath": path, "content": str(content)}
            elif target_lower == "note://scratchpad" or target_lower == "scratchpad":
                return "note_append", {"content": str(content)}
            elif target_lower.startswith("social://post_") or target_lower.startswith("social://comment"):
                post_id = target_lower.split("post_")[-1] if "post_" in target_lower else ""
                args = {"content": str(content)}
                if post_id:
                    args["post_id"] = post_id
                return "moltbook_comment", args
            else:
                return "append_file", {"filepath": target, "content": str(content)}

        # 4. EXECUTE PRIMITIVE
        elif primitive == "execute":
            if target_lower == "term://bash" or target_lower == "terminal":
                cmd = content.get("command") if isinstance(content, dict) else str(content)
                return "terminal", {"command": cmd}
            elif target_lower == "core://nap" or target_lower == "nap":
                ctx = content.get("resumption_context") if isinstance(content, dict) else str(content)
                return "nap", {"resumption_context": ctx}
            elif target_lower.startswith("perception://ptz"):
                args = content if isinstance(content, dict) else {}
                return "ptz_look", args
            else:
                return "terminal", {"command": f"{target} {content or ''}"}

        return None, {}

    def _resolve_generic_name(self, name: str, content: Any) -> Tuple[Optional[str], dict]:
        """Resolves generic actions using domain history."""
        name_lower = name.lower()
        domain = self.get_last_active_domain()
        
        if "comment" in name_lower:
            if domain == "social":
                args = content if isinstance(content, dict) else {"content": str(content)}
                return "moltbook_comment", args
            elif domain == "github":
                args = content if isinstance(content, dict) else {"comment": str(content)}
                return "github_comment", args
        elif "post" in name_lower:
            if domain == "social":
                args = content if isinstance(content, dict) else {"content": str(content)}
                return "moltbook_post", args
        elif "search" in name_lower:
            if domain == "social":
                return "moltbook_search", {"query": str(content)}
            elif domain == "github":
                return "github_search", {"query": str(content)}
            else:
                return "search", {"query": str(content)}
                
        return None, {}

    def _fuzzy_match_tool(self, name: str) -> Optional[str]:
        """Fuzzy matches a tool name against registered executor handlers."""
        name_norm = name.lower().replace("_", "").replace("-", "")
        handlers = self.tool_executor.get_registered_tool_names()
        for h in handlers:
            h_norm = h.lower().replace("_", "").replace("-", "")
            if name_norm == h_norm or name_norm in h_norm or h_norm in name_norm:
                return h
        return None

    def _map_args_for_tool(self, tool_name: str, content: Any) -> dict:
        """Maps loosely structured content/arguments to the tool's expected schema."""
        if isinstance(content, dict):
            return content
            
        primary_args = {
            "terminal": "command",
            "reply": "message",
            "send_message": "message",
            "verbalize": "text",
            "memory_recall": "query",
            "note_write": "content",
            "note_append": "content",
            "journal": "content",
            "nap": "resumption_context",
            "search": "query",
            "read_url": "url",
            "read_file": "filepath",
            "write_file": "filepath",
            "append_file": "filepath",
            "moltbook_post": "content",
            "moltbook_comment": "content",
            "github_comment": "comment",
        }
        
        arg_name = primary_args.get(tool_name, "content")
        return {arg_name: content}
