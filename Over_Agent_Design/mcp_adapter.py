"""
MCP (Model Context Protocol) Client Adapter — Subconscious Over-Agent System.

Provides stdio JSON-RPC 2.0 client implementation for connecting Sub-Orchestrators
(ResearcherSubOrchestrator & ExecutorSubOrchestrator) to external MCP servers.
Keeps MCP tool schemas encapsulated inside sub-passes, maintaining an ultra-slim (~80 token)
executive conductor prompt.
"""

import os
import sys
import json
import subprocess
from typing import Dict, List, Any, Optional

class MCPClientAdapter:
    """
    Stdio JSON-RPC 2.0 Client for Model Context Protocol (MCP) Servers.
    Launches MCP server process via command line and communicates via stdin/stdout.
    """
    def __init__(self, server_name: str, command: List[str], env: Optional[Dict[str, str]] = None):
        self.server_name = server_name
        self.command = command
        self.env = env or os.environ.copy()
        self.proc: Optional[subprocess.Popen] = None
        self.request_id = 0
        self.tools: List[Dict[str, Any]] = []
        self._connected = False

    def connect(self, timeout_s: float = 5.0) -> bool:
        """Launches the MCP server subprocess and sends initialize JSON-RPC handshake."""
        try:
            self.proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=self.env,
                bufsize=1
            )
            
            # Send 'initialize' JSON-RPC request
            init_resp = self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "HelixOverAgent", "version": "1.0.0"}
            }, timeout_s=timeout_s)
            
            if init_resp and "result" in init_resp:
                self._connected = True
                # Send 'notifications/initialized'
                self._send_notification("notifications/initialized", {})
                # Cache available tools
                self.refresh_tools()
                return True
        except Exception as e:
            print(f"[MCP Warning] Could not connect to MCP server '{self.server_name}': {e}")
        return False

    def refresh_tools(self) -> List[Dict[str, Any]]:
        """Queries MCP server for available tools via 'tools/list'."""
        if not self._connected:
            return []
        resp = self._send_request("tools/list", {})
        if resp and "result" in resp and "tools" in resp["result"]:
            self.tools = resp["result"]["tools"]
        return self.tools

    def call_tool(self, name: str, arguments: Dict[str, Any], timeout_s: float = 15.0) -> Dict[str, Any]:
        """Executes a tool on the MCP server via 'tools/call'."""
        if not self._connected:
            return {"isError": True, "content": [{"type": "text", "text": f"MCP Server '{self.server_name}' not connected."}]}
            
        resp = self._send_request("tools/call", {
            "name": name,
            "arguments": arguments
        }, timeout_s=timeout_s)
        
        if resp and "result" in resp:
            return resp["result"]
        elif resp and "error" in resp:
            return {"isError": True, "content": [{"type": "text", "text": f"MCP Error: {resp['error'].get('message')}"}]}
        return {"isError": True, "content": [{"type": "text", "text": "MCP Tool execution timed out or returned invalid response."}]}

    def disconnect(self):
        """Terminates the MCP server process cleanly."""
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2.0)
            except Exception:
                pass
            self.proc = None
        self._connected = False

    def _send_request(self, method: str, params: Dict[str, Any], timeout_s: float = 5.0) -> Optional[Dict[str, Any]]:
        if not self.proc or not self.proc.stdin or not self.proc.stdout:
            return None
            
        self.request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params
        }
        
        try:
            json_line = json.dumps(payload) + "\n"
            self.proc.stdin.write(json_line)
            self.proc.stdin.flush()
            
            # Read stdout line
            response_line = self.proc.stdout.readline()
            if response_line.strip():
                return json.loads(response_line)
        except Exception as e:
            print(f"[MCP Error] Protocol exchange failed on '{self.server_name}': {e}")
        return None

    def _send_notification(self, method: str, params: Dict[str, Any]):
        if not self.proc or not self.proc.stdin:
            return
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        try:
            json_line = json.dumps(payload) + "\n"
            self.proc.stdin.write(json_line)
            self.proc.stdin.flush()
        except Exception:
            pass


class MCPRegistry:
    """
    Registry for managing multiple active MCP server connections across Sub-Orchestrators.
    """
    def __init__(self):
        self.servers: Dict[str, MCPClientAdapter] = {}

    def register_server(self, name: str, command: List[str], env: Optional[Dict[str, str]] = None) -> bool:
        client = MCPClientAdapter(name, command, env=env)
        if client.connect():
            self.servers[name] = client
            print(f"  ✓ Connected MCP Server '{name}' ({len(client.tools)} tools available)")
            return True
        return False

    def get_all_tools(self) -> Dict[str, List[Dict[str, Any]]]:
        all_tools = {}
        for name, client in self.servers.items():
            all_tools[name] = client.tools
        return all_tools

    def call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if server_name in self.servers:
            return self.servers[server_name].call_tool(tool_name, arguments)
        return {"isError": True, "content": [{"type": "text", "text": f"Server '{server_name}' not registered."}]}

    def disconnect_all(self):
        for client in self.servers.values():
            client.disconnect()
        self.servers.clear()
