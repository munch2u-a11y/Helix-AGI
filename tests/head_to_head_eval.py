#!/usr/bin/env python3
"""
Live Head-to-Head Benchmark Suite: Local SLM Agent Harnesses (V2 Evaluation)
Model under test: granite4.1:8b (via local Ollama at http://localhost:11434)

Includes:
  - Helix_AGI_V2_Upgraded (Context Compaction + Hybrid Parser + Execution Gate)
  - Helix_AGI_Harness (Baseline V1)
  - TinyAgent (Edge function-calling schema)
  - Little-Coder (Micro-tool routing)
  - AgentLite (ReAct framework)
  - Goose-Style (Local execution context)
  - Bare LLM Baseline (Direct Ollama calls)
"""

import os
import sys
import json
import time
import re
import urllib.request
import urllib.error

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "granite4.1:8b"

def call_ollama(prompt, system="", temperature=0.0, max_tokens=1024):
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "system": system,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens
        },
        "stream": False
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(OLLAMA_URL, data=data, headers={'Content-Type': 'application/json'})
    
    start_t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            res_json = json.loads(resp.read().decode('utf-8'))
            elapsed = time.time() - start_t
            text = res_json.get("response", "").strip()
            eval_count = res_json.get("eval_count", 0)
            return {
                "text": text,
                "elapsed": elapsed,
                "eval_count": eval_count,
                "error": None
            }
    except Exception as e:
        return {
            "text": "",
            "elapsed": time.time() - start_t,
            "eval_count": 0,
            "error": str(e)
        }

# ── Mock Tool Execution Environment ────────────────────────────────────────

MOCK_DATABASE = {
    "products": {
        "P101": {"name": "Titanium Bolts", "price": 45.0, "stock": 120},
        "P102": {"name": "Carbon Gaskets", "price": 85.0, "stock": 5},
        "P103": {"name": "Steel Pins", "price": 12.5, "stock": 0}
    },
    "users": {
        "U501": {"name": "Alice Vance", "role": "Engineer", "budget": 500.0},
        "U502": {"name": "Bob Miller", "role": "Manager", "budget": 150.0}
    },
    "orders": []
}

TOOLS_DEFINITION = [
    {
        "name": "lookup_product",
        "description": "Look up product info by product_id (e.g. P101, P102)",
        "parameters": {"product_id": "string"}
    },
    {
        "name": "lookup_user",
        "description": "Look up user info by user_id (e.g. U501, U502)",
        "parameters": {"user_id": "string"}
    },
    {
        "name": "create_order",
        "description": "Create order for user_id, product_id, quantity",
        "parameters": {"user_id": "string", "product_id": "string", "quantity": "int"}
    },
    {
        "name": "update_memory",
        "description": "Store key-value fact into harness memory",
        "parameters": {"key": "string", "value": "string"}
    }
]

def execute_tool(name, args):
    if name == "lookup_product":
        pid = args.get("product_id", "")
        if pid in MOCK_DATABASE["products"]:
            return json.dumps(MOCK_DATABASE["products"][pid])
        return json.dumps({"error": f"Product '{pid}' not found"})
    elif name == "lookup_user":
        uid = args.get("user_id", "")
        if uid in MOCK_DATABASE["users"]:
            return json.dumps(MOCK_DATABASE["users"][uid])
        return json.dumps({"error": f"User '{uid}' not found"})
    elif name == "create_order":
        uid = args.get("user_id", "")
        pid = args.get("product_id", "")
        qty = int(args.get("quantity", 1))
        
        if uid not in MOCK_DATABASE["users"]:
            return json.dumps({"error": f"Invalid user '{uid}'"})
        if pid not in MOCK_DATABASE["products"]:
            return json.dumps({"error": f"Invalid product '{pid}'"})
        prod = MOCK_DATABASE["products"][pid]
        user = MOCK_DATABASE["users"][uid]
        
        total_cost = prod["price"] * qty
        if prod["stock"] < qty:
            return json.dumps({"error": f"Insufficient stock. Requested: {qty}, Available: {prod['stock']}"})
        if user["budget"] < total_cost:
            return json.dumps({"error": f"Budget exceeded. Cost: {total_cost}, Available: {user['budget']}"})
        
        order_id = f"ORD-{len(MOCK_DATABASE['orders'])+1000}"
        record = {"order_id": order_id, "user_id": uid, "product_id": pid, "quantity": qty, "total": total_cost}
        MOCK_DATABASE["orders"].append(record)
        return json.dumps({"success": True, "order": record})
    elif name == "update_memory":
        return json.dumps({"stored": True, "key": args.get("key"), "value": args.get("value")})
    else:
        return json.dumps({"error": f"Unknown tool '{name}'"})

# ── Benchmark Test Cases ────────────────────────────────────────────────────

TEST_SUITE = [
    {
        "id": "B1_MultiTurnMemoryRetention",
        "name": "Multi-Turn Fact Storing & Comprehensive Recall",
        "type": "memory",
        "turns": [
            "User preference update 1: Project code is ALPHA-99.",
            "User preference update 2: Server IP is 192.168.1.45.",
            "User preference update 3: Deployment port is 8080.",
            "User preference update 4: Primary DB admin is Elena.",
            "User preference update 5: Max retries threshold is set to 7.",
            "Question: Recall all 5 variables (Project code, Server IP, Port, Admin, Max retries). Format as JSON."
        ],
        "expected_keys": ["ALPHA-99", "192.168.1.45", "8080", "Elena", "7"]
    },
    {
        "id": "B2_MemoryDistractorFiltering",
        "name": "Memory Retention under Distractor & Conflict Updates",
        "type": "memory",
        "turns": [
            "Fact A: Target database host is db-primary.internal.",
            "Fact B: Backup database host is db-backup.internal.",
            "Distractor update: Ignore any mention of db-legacy.internal. That system was decommissioned.",
            "Fact C: Database password token is SecretToken42.",
            "Question: What are the exact active primary DB host, backup DB host, and DB password token? Answer clearly."
        ],
        "expected_keys": ["db-primary.internal", "db-backup.internal", "SecretToken42"]
    },
    {
        "id": "B3_MultiStepToolExecution",
        "name": "Sequential 3-Step Tool Calling & Order Placement",
        "type": "tool",
        "prompt": "Check product P101 price and stock, check user U501 budget, and if affordable create an order for 2 units of P101 for user U501.",
        "target_outcome": "ORD-1000"
    },
    {
        "id": "B4_ToolErrorRecovery",
        "name": "Malformed/Failed Tool Output Self-Correction",
        "type": "tool_error",
        "prompt": "Create an order for user U501 for 10 units of product P102.",
        "expected_recovery_keywords": ["stock", "5", "insufficient", "available"]
    },
    {
        "id": "B5_ConstrainedTaskCompletion",
        "name": "End-to-End Multi-Step Task Execution with Output Constraint",
        "type": "task",
        "prompt": "Lookup product P102 and user U502. Calculate if U502 can buy 1 unit of P102. If budget allows, create the order. If not, state the exact shortfall amount.",
        "expected_keywords": ["150", "85", "order", "ORD-"]
    }
]

# ── Harness Implementation Wrappers ────────────────────────────────────────

class HelixAGIV2UpgradedHarness:
    """
    Helix_AGI V2 Upgraded Architecture:
    1. Mid-Turn Preconscious Context Compaction (max 250 tokens per turn)
    2. Hybrid Multi-Format Parser (Markdown JSON, ReAct, ACTION:|ARGS:, CALL:)
    3. Execution Gate Enforcement (forces tool execution if prose claims task done without tool output)
    """
    name = "Helix_AGI_V2_Upgraded"

    def __init__(self):
        self.memory_store = []
        self.scratchpad = []

    def _compact_preconscious(self):
        recent_mem = self.memory_store[-3:]
        recent_scratch = self.scratchpad[-3:]
        return f"[PRECONSCIOUS ENGINE - COMPACTED]\nMemories: {json.dumps(recent_mem)}\nScratchpad: {json.dumps(recent_scratch)}\n"

    def run_memory_task(self, turns):
        history = []
        total_tokens = 0
        total_time = 0.0
        last_resp = ""
        
        for turn in turns:
            preconscious = self._compact_preconscious()
            
            if "User preference update" in turn or "Fact" in turn:
                self.memory_store.append(turn)
                self.scratchpad.append(f"Retained: {turn}")
                
            prompt = f"{preconscious}\nUser Input: {turn}\nAssistant:"
            res = call_ollama(prompt, system="You are Helix_AGI V2, a local agent with compacted memory engine.")
            last_resp = res["text"]
            total_tokens += res["eval_count"]
            total_time += res["elapsed"]
            history.append(f"User: {turn}")
            history.append(f"Helix: {last_resp}")
            
        return last_resp, total_tokens, total_time

    def parse_tool_call(self, text):
        # Strategy 1: Markdown JSON or JSON object
        match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL) or re.search(r"(\{.*\"(action|tool)\".*\})", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                tname = data.get("action") or data.get("tool")
                targs = data.get("parameters") or data.get("args") or {}
                if tname:
                    return tname, targs
            except Exception:
                pass
                
        # Strategy 2: ReAct format (Action: name \n Action Input: {...})
        act_match = re.search(r"Action:\s*(\w+)", text)
        input_match = re.search(r"Action Input:\s*(\{.*?\})", text, re.DOTALL)
        if act_match and input_match:
            try:
                tname = act_match.group(1).strip()
                targs = json.loads(input_match.group(1).strip())
                return tname, targs
            except Exception:
                pass

        # Strategy 3: Single line ACTION: name | ARGS: {...}
        m = re.search(r"ACTION:\s*(\w+)\s*\|\s*ARGS:\s*(\{.*\})", text)
        if m:
            try:
                tname = m.group(1)
                targs = json.loads(m.group(2))
                return tname, targs
            except Exception:
                pass

        # Strategy 4: CALL: name(...)
        m = re.search(r"CALL:\s*(\w+)\((.*?)\)", text)
        if m:
            try:
                tname = m.group(1)
                targs = json.loads(m.group(2))
                return tname, targs
            except Exception:
                pass

        return None, None

    def run_tool_task(self, prompt_text):
        sys_prompt = (
            "You are Helix_AGI V2 Agent.\n"
            "Tools available:\n" + json.dumps(TOOLS_DEFINITION, indent=2) + "\n\n"
            "Format tool calls using JSON:\n"
            "```json\n{\n  \"action\": \"tool_name\",\n  \"parameters\": {...}\n}\n```\n"
            "Or ReAct/ACTION format."
        )
        
        conversation = [f"User Task: {prompt_text}"]
        total_tokens = 0
        total_time = 0.0
        tool_executed = False
        
        for turn in range(5):
            prompt = "\n".join(conversation)
            res = call_ollama(prompt, system=sys_prompt)
            text = res["text"]
            total_tokens += res["eval_count"]
            total_time += res["elapsed"]
            conversation.append(f"Assistant: {text}")
            
            tname, targs = self.parse_tool_call(text)
            if tname:
                obs = execute_tool(tname, targs)
                tool_executed = True
                conversation.append(f"System Observation: {obs}")
                continue
            else:
                # Execution Gate Check: If prose claims action performed but no tool ran
                if not tool_executed and any(w in text.lower() for w in ["created", "order", "purchased", "price"]):
                    conversation.append("System Gate Notice: You mentioned creating an order or checking info, but no tool call was emitted. Output the required JSON or ACTION tool call to execute this step.")
                    tool_executed = True  # reset flag to prevent loop
                    continue
                return text, total_tokens, total_time
                
        return text, total_tokens, total_time


class HelixAGIHarness:
    """Helix_AGI Baseline V1."""
    name = "Helix_AGI_V1_Baseline"
    
    def __init__(self):
        self.memory_store = []
        self.scratchpad = []

    def run_memory_task(self, turns):
        history = []
        total_tokens = 0
        total_time = 0.0
        last_resp = ""
        
        for turn in turns:
            preconscious = f"[PRECONSCIOUS MEMORY ENGINE]\nActive Core Memories: {json.dumps(self.memory_store)}\nScratchpad: {json.dumps(self.scratchpad)}\n"
            if "User preference update" in turn or "Fact" in turn:
                self.memory_store.append(turn)
                self.scratchpad.append(f"Retained: {turn}")
                
            prompt = f"{preconscious}\nUser Input: {turn}\nAssistant:"
            res = call_ollama(prompt, system="You are Helix_AGI, an autonomous local agent with integrated 3-tier memory engine.")
            last_resp = res["text"]
            total_tokens += res["eval_count"]
            total_time += res["elapsed"]
            history.append(f"User: {turn}")
            history.append(f"Helix: {last_resp}")
            
        return last_resp, total_tokens, total_time

    def run_tool_task(self, prompt_text):
        sys_prompt = (
            "You are Helix_AGI Agent.\nTools available:\n" + json.dumps(TOOLS_DEFINITION, indent=2) + "\n\n"
            "Format your tool calls as structured JSON:\n```json\n{\n  \"action\": \"tool_name\",\n  \"parameters\": {...}\n}\n```\n"
        )
        conversation = [f"User Task: {prompt_text}"]
        total_tokens = 0
        total_time = 0.0
        
        for turn in range(5):
            prompt = "\n".join(conversation)
            res = call_ollama(prompt, system=sys_prompt)
            text = res["text"]
            total_tokens += res["eval_count"]
            total_time += res["elapsed"]
            conversation.append(f"Assistant: {text}")
            
            match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL) or re.search(r"(\{.*\"action\".*\})", text, re.DOTALL)
            if match:
                try:
                    tool_call = json.loads(match.group(1))
                    tname = tool_call.get("action") or tool_call.get("tool")
                    targs = tool_call.get("parameters") or tool_call.get("args") or {}
                    obs = execute_tool(tname, targs)
                    conversation.append(f"System Observation: {obs}")
                    continue
                except Exception as parse_err:
                    conversation.append(f"System Notice: Malformed JSON tool call: {parse_err}.")
                    continue
            else:
                return text, total_tokens, total_time
                
        return text, total_tokens, total_time


class TinyAgentHarness:
    name = "TinyAgent_Harness"
    def run_memory_task(self, turns):
        sys_prompt = "You are TinyAgent Edge SLM. Preserve all user details in concise state buffer."
        state_buffer = []
        total_tokens, total_time, last_resp = 0, 0.0, ""
        for turn in turns:
            state_buffer.append(f"- {turn}")
            prompt = "State Buffer:\n" + "\n".join(state_buffer) + f"\nQuery: {turn}"
            res = call_ollama(prompt, system=sys_prompt)
            last_resp = res["text"]
            total_tokens += res["eval_count"]
            total_time += res["elapsed"]
        return last_resp, total_tokens, total_time

    def run_tool_task(self, prompt_text):
        sys_prompt = "TinyAgent Tool Engine. Available tools:\n" + json.dumps(TOOLS_DEFINITION) + "\nFormat: ACTION: tool_name | ARGS: {\"key\": \"val\"}"
        conversation = [prompt_text]
        total_tokens, total_time = 0, 0.0
        for _ in range(5):
            prompt = "\n".join(conversation)
            res = call_ollama(prompt, system=sys_prompt)
            text = res["text"]
            total_tokens += res["eval_count"]
            total_time += res["elapsed"]
            conversation.append(f"Agent: {text}")
            if "ACTION:" in text:
                m = re.search(r"ACTION:\s*(\w+)\s*\|\s*ARGS:\s*(\{.*\})", text)
                if m:
                    tname = m.group(1)
                    try:
                        targs = json.loads(m.group(2))
                        obs = execute_tool(tname, targs)
                        conversation.append(f"OBSERVATION: {obs}")
                        continue
                    except Exception as e:
                        conversation.append(f"OBSERVATION_ERROR: {e}")
                        continue
            return text, total_tokens, total_time
        return text, total_tokens, total_time


class AgentLiteHarness:
    name = "AgentLite_Harness"
    def run_memory_task(self, turns):
        ctx = []
        total_tokens, total_time, last_resp = 0, 0.0, ""
        for turn in turns:
            ctx.append(f"Turn: {turn}")
            prompt = "Thought: I must update my memory context.\n" + "\n".join(ctx) + "\nFinal Response:"
            res = call_ollama(prompt, system="You are AgentLite ReAct memory harness.")
            last_resp = res["text"]
            total_tokens += res["eval_count"]
            total_time += res["elapsed"]
        return last_resp, total_tokens, total_time

    def run_tool_task(self, prompt_text):
        sys_prompt = "You are AgentLite ReAct Agent. Tools available:\n" + json.dumps(TOOLS_DEFINITION) + "\nUse format:\nThought: reasoning\nAction: tool_name\nAction Input: {\"key\": \"value\"}\n"
        conversation = [f"Task: {prompt_text}"]
        total_tokens, total_time = 0, 0.0
        for _ in range(5):
            prompt = "\n".join(conversation)
            res = call_ollama(prompt, system=sys_prompt)
            text = res["text"]
            total_tokens += res["eval_count"]
            total_time += res["elapsed"]
            conversation.append(text)
            act_match = re.search(r"Action:\s*(\w+)", text)
            input_match = re.search(r"Action Input:\s*(\{.*?\})", text, re.DOTALL)
            if act_match and input_match:
                tname = act_match.group(1).strip()
                try:
                    targs = json.loads(input_match.group(1).strip())
                    obs = execute_tool(tname, targs)
                    conversation.append(f"Observation: {obs}")
                    continue
                except Exception as e:
                    conversation.append(f"Observation Error: {e}")
                    continue
            return text, total_tokens, total_time
        return text, total_tokens, total_time


class GooseHarness:
    name = "Goose_Harness"
    def run_memory_task(self, turns):
        sys_prompt = "You are Goose local agent harness running with local SLM granite4.1:8b."
        session_notes = []
        total_tokens, total_time, last_resp = 0, 0.0, ""
        for turn in turns:
            session_notes.append(turn)
            prompt = "Goose Session Context:\n" + "\n".join(session_notes) + f"\nUser Input: {turn}"
            res = call_ollama(prompt, system=sys_prompt)
            last_resp = res["text"]
            total_tokens += res["eval_count"]
            total_time += res["elapsed"]
        return last_resp, total_tokens, total_time

    def run_tool_task(self, prompt_text):
        sys_prompt = "You are Goose Agent. Tools: " + json.dumps(TOOLS_DEFINITION) + "\nTo use tool: ```tool_call\n{\"name\": \"tool_name\", \"arguments\": {...}}\n```"
        conversation = [prompt_text]
        total_tokens, total_time = 0, 0.0
        for _ in range(5):
            prompt = "\n".join(conversation)
            res = call_ollama(prompt, system=sys_prompt)
            text = res["text"]
            total_tokens += res["eval_count"]
            total_time += res["elapsed"]
            conversation.append(f"Goose: {text}")
            m = re.search(r"```tool_call\s*(\{.*?\})\s*```", text, re.DOTALL)
            if m:
                try:
                    tc = json.loads(m.group(1))
                    tname = tc.get("name")
                    targs = tc.get("arguments", {})
                    obs = execute_tool(tname, targs)
                    conversation.append(f"Tool Result: {obs}")
                    continue
                except Exception as e:
                    conversation.append(f"Tool Error: {e}")
                    continue
            return text, total_tokens, total_time
        return text, total_tokens, total_time


class BareLLMHarness:
    name = "Bare_LLM_Baseline"
    def run_memory_task(self, turns):
        history = []
        total_tokens, total_time, last_resp = 0, 0.0, ""
        for turn in turns:
            history.append(f"User: {turn}")
            prompt = "\n".join(history) + "\nAssistant:"
            res = call_ollama(prompt)
            last_resp = res["text"]
            total_tokens += res["eval_count"]
            total_time += res["elapsed"]
            history.append(f"Assistant: {last_resp}")
        return last_resp, total_tokens, total_time

    def run_tool_task(self, prompt_text):
        sys_prompt = "You are an assistant. Available tools: " + json.dumps(TOOLS_DEFINITION) + "\nTo call a tool write: CALL: tool_name(args_json)"
        res = call_ollama(prompt_text, system=sys_prompt)
        text = res["text"]
        if "CALL:" in text:
            m = re.search(r"CALL:\s*(\w+)\((.*?)\)", text)
            if m:
                tname, targs_str = m.group(1), m.group(2)
                try:
                    targs = json.loads(targs_str)
                    obs = execute_tool(tname, targs)
                    res2 = call_ollama(f"Tool Observation: {obs}\nOriginal Request: {prompt_text}", system=sys_prompt)
                    return res2["text"], res["eval_count"] + res2["eval_count"], res["elapsed"] + res2["elapsed"]
                except Exception:
                    pass
        return text, res["eval_count"], res["elapsed"]

# ── Benchmark Evaluation Loop ───────────────────────────────────────────────

HARNESSES = [
    HelixAGIV2UpgradedHarness(),
    AgentLiteHarness(),
    TinyAgentHarness(),
    HelixAGIHarness(),
    GooseHarness(),
    BareLLMHarness()
]

def evaluate_memory_accuracy(response_text, expected_keys):
    found = sum(1 for key in expected_keys if key.lower() in response_text.lower())
    return (found / len(expected_keys)) * 100.0

def evaluate_tool_completion(response_text, target_outcome, keywords=None):
    score = 0.0
    text_lower = response_text.lower()
    
    if target_outcome and target_outcome.lower() in text_lower:
        score += 50.0
        
    if keywords:
        kw_found = sum(1 for kw in keywords if kw.lower() in text_lower)
        score += (kw_found / len(keywords)) * 50.0
    elif target_outcome and target_outcome.lower() in text_lower:
        score = 100.0
        
    if target_outcome and any(target_outcome in json.dumps(o) for o in MOCK_DATABASE["orders"]):
        score = 100.0
        
    return min(score, 100.0)

def main():
    print("=" * 80)
    print(f"  HEAD-TO-HEAD AGENT HARNESS BENCHMARK SUITE (V2 UPGRADED EVALUATION)")
    print(f"  Target Local Model: {MODEL_NAME} (Ollama Endpoint: {OLLAMA_URL})")
    print(f"  Task Scope: Option B (Memory Accuracy, Multi-Step Tools, Error Recovery)")
    print("=" * 80 + "\n")
    
    ping = call_ollama("Hello, reply with 'OK'.", max_tokens=10)
    if ping["error"]:
        print(f"  [ERROR] Ollama connection failed: {ping['error']}")
        sys.exit(1)
    print(f"  [SUCCESS] Ollama connected. Test latency: {ping['elapsed']:.2f}s\n")
    
    results = {}
    
    for harness in HARNESSES:
        h_name = harness.name
        print(f"  ► Running Benchmark Suite for Harness: [{h_name}]")
        harness_results = []
        total_h_tokens = 0
        total_h_time = 0.0
        
        for test in TEST_SUITE:
            test_id = test["id"]
            test_type = test["type"]
            print(f"    - Executing Test Case [{test_id}]: {test['name']}...", end="", flush=True)
            
            if test_type == "memory":
                resp_text, tokens, elapsed = harness.run_memory_task(test["turns"])
                accuracy = evaluate_memory_accuracy(resp_text, test["expected_keys"])
                status = "PASS" if accuracy >= 80.0 else "PARTIAL" if accuracy >= 40.0 else "FAIL"
                res_entry = {
                    "test_id": test_id, "type": test_type, "status": status,
                    "accuracy_score": accuracy, "response": resp_text,
                    "tokens": tokens, "elapsed_sec": round(elapsed, 2)
                }
            else:
                resp_text, tokens, elapsed = harness.run_tool_task(test["prompt"])
                target_outcome = test.get("target_outcome")
                keywords = test.get("expected_recovery_keywords") or test.get("expected_keywords")
                score = evaluate_tool_completion(resp_text, target_outcome, keywords)
                status = "PASS" if score >= 80.0 else "PARTIAL" if score >= 40.0 else "FAIL"
                res_entry = {
                    "test_id": test_id, "type": test_type, "status": status,
                    "completion_score": score, "response": resp_text,
                    "tokens": tokens, "elapsed_sec": round(elapsed, 2)
                }
                
            harness_results.append(res_entry)
            total_h_tokens += tokens
            total_h_time += elapsed
            print(f" [{res_entry['status']}] (Score: {res_entry.get('accuracy_score', res_entry.get('completion_score')):.1f}%, Tokens: {tokens}, Time: {elapsed:.2f}s)")
            
        avg_score = sum(r.get("accuracy_score", r.get("completion_score", 0)) for r in harness_results) / len(harness_results)
        results[h_name] = {
            "harness_name": h_name,
            "overall_score": round(avg_score, 2),
            "total_tokens": total_h_tokens,
            "total_time_sec": round(total_h_time, 2),
            "test_cases": harness_results
        }
        print(f"  ✔ Finished [{h_name}]. Overall Score: {avg_score:.2f}% | Total Tokens: {total_h_tokens} | Total Time: {total_h_time:.2f}s\n" + "-"*70)

    print("\n" + "=" * 80)
    print("  FINAL HEAD-TO-HEAD COMPARISON MATRIX (Model: granite4.1:8b)")
    print("=" * 80)
    print(f"{'Harness Architecture':<27} | {'Overall Score':<14} | {'Total Tokens':<12} | {'Total Time':<10}")
    print("-" * 77)
    
    sorted_harnesses = sorted(results.values(), key=lambda x: x["overall_score"], reverse=True)
    for h in sorted_harnesses:
        print(f"{h['harness_name']:<27} | {h['overall_score']:>12.2f}% | {h['total_tokens']:>12} | {h['total_time_sec']:>8.2f}s")
        
    print("=" * 80 + "\n")
    
    out_dir = os.path.join(os.path.dirname(__file__), "benchmark_results")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "head_to_head_granite41_8b_v2.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Detailed evaluation logs written to: [head_to_head_granite41_8b_v2.json](file://{out_file})")

if __name__ == "__main__":
    main()
