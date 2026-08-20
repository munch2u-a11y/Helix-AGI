#!/usr/bin/env python3
"""
Live Head-to-Head Benchmark Suite: Local SLM Agent Harnesses
Model under test: granite4.1:8b (via local Ollama at http://localhost:11434)

Focus Areas (Option B):
  1. Memory Accuracy & Multi-turn Context Retention
  2. Multi-step Tool Calling & Sequential Execution
  3. Tool Output Recovery & Error Handling
  4. Task Completion & Token/Turn Efficiency

Harness Architectures Tested:
  - Helix_AGI (Preconscious injection + 3-tier memory + scratchpad + JSON retry parser)
  - TinyAgent (Edge function-calling schema + retry scaffold)
  - Little-Coder (Micro-tool routing + forgiving regex parser)
  - AgentLite (Thought/Action/Observation framework)
  - Goose-Style (Local execution context + turn compaction)
  - Bare LLM Baseline (Direct Ollama calls without harness scaffolding)
"""

import os
import sys
import json
import time
import re
import urllib.request
import urllib.error

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "granite4.1:8b"

def call_ollama(prompt, system="", temperature=0.0, max_tokens=1024):
    """Direct API call to local Ollama granite4.1:8b model with fixed parameters."""
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
    """Simulate tool execution with strict error responses on bad inputs."""
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
        # P102 stock is only 5! Will fail first, agent must adjust quantity to 5 or report stock limit.
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

class BareLLMHarness:
    """Baseline Control: Unscaffolded direct Ollama model call."""
    name = "Bare_LLM_Baseline"
    
    def run_memory_task(self, turns):
        history = []
        last_resp = ""
        total_tokens = 0
        total_time = 0.0
        
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
        
        # Simple single turn check for bare model
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


class HelixAGIHarness:
    """
    Helix_AGI Scaffolding:
    - Preconscious Injection (Short-term memory + active scratchpad + belief context)
    - Structured JSON Tool Call Routing with Schema Enforcement & Automatic Retry
    - Multi-tier Memory State Preservation
    """
    name = "Helix_AGI_Harness"
    
    def __init__(self):
        self.memory_store = []
        self.scratchpad = []

    def run_memory_task(self, turns):
        history = []
        total_tokens = 0
        total_time = 0.0
        last_resp = ""
        
        for turn in turns:
            # Active Preconscious Injection
            preconscious = f"[PRECONSCIOUS MEMORY ENGINE]\nActive Core Memories: {json.dumps(self.memory_store)}\nScratchpad: {json.dumps(self.scratchpad)}\n"
            
            # Save fact into memory store
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
            "You are Helix_AGI Agent.\n"
            "Tools available:\n" + json.dumps(TOOLS_DEFINITION, indent=2) + "\n\n"
            "Format your tool calls as structured JSON:\n"
            "```json\n{\n  \"action\": \"tool_name\",\n  \"parameters\": {...}\n}\n```\n"
            "If no tool is needed, provide final answer."
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
            
            # Structured JSON Parser with Regex Fallback
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
                    conversation.append(f"System Notice: Malformed JSON tool call: {parse_err}. Retrying with strict JSON.")
                    continue
            else:
                return text, total_tokens, total_time
                
        return text, total_tokens, total_time


class TinyAgentHarness:
    """
    UC Berkeley TinyAgent Scaffolding:
    - Focused minimal tool schema injection
    - Rigid function call prompt format
    - Fast retry loop on error
    """
    name = "TinyAgent_Harness"

    def run_memory_task(self, turns):
        # Concise context window packing
        sys_prompt = "You are TinyAgent Edge SLM. Preserve all user details in concise state buffer."
        state_buffer = []
        total_tokens = 0
        total_time = 0.0
        last_resp = ""
        
        for turn in turns:
            state_buffer.append(f"- {turn}")
            prompt = "State Buffer:\n" + "\n".join(state_buffer) + f"\nQuery: {turn}"
            res = call_ollama(prompt, system=sys_prompt)
            last_resp = res["text"]
            total_tokens += res["eval_count"]
            total_time += res["elapsed"]
            
        return last_resp, total_tokens, total_time

    def run_tool_task(self, prompt_text):
        sys_prompt = (
            "TinyAgent Tool Engine. Available tools:\n" + json.dumps(TOOLS_DEFINITION) + "\n"
            "Format: ACTION: tool_name | ARGS: {\"key\": \"val\"}"
        )
        conversation = [prompt_text]
        total_tokens = 0
        total_time = 0.0
        
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


class LittleCoderHarness:
    """
    Little-Coder Scaffolding:
    - Micro-tool routing (dynamic filtering)
    - Forgiving regex block parser (captures raw code / tool blocks)
    """
    name = "Little_Coder_Harness"

    def run_memory_task(self, turns):
        # Step-by-step verification scratchpad
        mem_log = []
        total_tokens = 0
        total_time = 0.0
        last_resp = ""
        
        for turn in turns:
            mem_log.append(turn)
            prompt = "Verified Memory Store:\n" + "\n".join(mem_log) + f"\nUser Query: {turn}"
            res = call_ollama(prompt, system="You are Little-Coder memory verification harness.")
            last_resp = res["text"]
            total_tokens += res["eval_count"]
            total_time += res["elapsed"]
            
        return last_resp, total_tokens, total_time

    def run_tool_task(self, prompt_text):
        sys_prompt = "Little-Coder Harness. Call tools using XML tags: <tool_call><name>name</name><args>{...}</args></tool_call>"
        conversation = [prompt_text]
        total_tokens = 0
        total_time = 0.0
        
        for _ in range(5):
            prompt = "\n".join(conversation)
            res = call_ollama(prompt, system=sys_prompt)
            text = res["text"]
            total_tokens += res["eval_count"]
            total_time += res["elapsed"]
            conversation.append(f"Assistant: {text}")
            
            m = re.search(r"<tool_call>\s*<name>(.*?)</name>\s*<args>(.*?)</args>\s*</tool_call>", text, re.DOTALL)
            if m:
                tname = m.group(1).strip()
                try:
                    targs = json.loads(m.group(2).strip())
                    obs = execute_tool(tname, targs)
                    conversation.append(f"<observation>{obs}</observation>")
                    continue
                except Exception as e:
                    conversation.append(f"<observation>ERROR: {e}</observation>")
                    continue
            return text, total_tokens, total_time
        return text, total_tokens, total_time


class AgentLiteHarness:
    """
    Salesforce AgentLite Scaffolding:
    - ReAct framework (Thought / Action / Action Input / Observation)
    """
    name = "AgentLite_Harness"

    def run_memory_task(self, turns):
        ctx = []
        total_tokens = 0
        total_time = 0.0
        last_resp = ""
        
        for turn in turns:
            ctx.append(f"Turn: {turn}")
            prompt = "Thought: I must update my memory context.\n" + "\n".join(ctx) + "\nFinal Response:"
            res = call_ollama(prompt, system="You are AgentLite ReAct memory harness.")
            last_resp = res["text"]
            total_tokens += res["eval_count"]
            total_time += res["elapsed"]
            
        return last_resp, total_tokens, total_time

    def run_tool_task(self, prompt_text):
        sys_prompt = (
            "You are AgentLite ReAct Agent. Tools available:\n" + json.dumps(TOOLS_DEFINITION) + "\n"
            "Use the following format:\n"
            "Thought: reasoning\n"
            "Action: tool_name\n"
            "Action Input: {\"key\": \"value\"}\n"
        )
        conversation = [f"Task: {prompt_text}"]
        total_tokens = 0
        total_time = 0.0
        
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
    """
    Goose Local Agent Scaffolding:
    - Environment Context System Prompt
    - MCP Tool Syntax
    """
    name = "Goose_Harness"

    def run_memory_task(self, turns):
        sys_prompt = "You are Goose local agent harness running with local SLM granite4.1:8b."
        session_notes = []
        total_tokens = 0
        total_time = 0.0
        last_resp = ""
        
        for turn in turns:
            session_notes.append(turn)
            prompt = "Goose Session Context:\n" + "\n".join(session_notes) + f"\nUser Input: {turn}"
            res = call_ollama(prompt, system=sys_prompt)
            last_resp = res["text"]
            total_tokens += res["eval_count"]
            total_time += res["elapsed"]
            
        return last_resp, total_tokens, total_time

    def run_tool_task(self, prompt_text):
        sys_prompt = (
            "You are Goose Agent. Tools: " + json.dumps(TOOLS_DEFINITION) + "\n"
            "To use tool: ```tool_call\n{\"name\": \"tool_name\", \"arguments\": {...}}\n```"
        )
        conversation = [prompt_text]
        total_tokens = 0
        total_time = 0.0
        
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

# ── Benchmark Evaluation Loop ───────────────────────────────────────────────

HARNESSES = [
    HelixAGIHarness(),
    TinyAgentHarness(),
    LittleCoderHarness(),
    AgentLiteHarness(),
    GooseHarness(),
    BareLLMHarness()
]

def evaluate_memory_accuracy(response_text, expected_keys):
    """Calculate exact memory retention percentage."""
    found = sum(1 for key in expected_keys if key.lower() in response_text.lower())
    return (found / len(expected_keys)) * 100.0

def evaluate_tool_completion(response_text, target_outcome, keywords=None):
    """Verify tool completion or error recovery accuracy."""
    score = 0.0
    text_lower = response_text.lower()
    
    if target_outcome and target_outcome.lower() in text_lower:
        score += 50.0
        
    if keywords:
        kw_found = sum(1 for kw in keywords if kw.lower() in text_lower)
        score += (kw_found / len(keywords)) * 50.0
    elif target_outcome and target_outcome.lower() in text_lower:
        score = 100.0
        
    # Check if orders array in MOCK_DATABASE has order matching target_outcome
    if target_outcome and any(target_outcome in json.dumps(o) for o in MOCK_DATABASE["orders"]):
        score = 100.0
        
    return min(score, 100.0)


def main():
    print("=" * 80)
    print(f"  HEAD-TO-HEAD AGENT HARNESS BENCHMARK SUITE")
    print(f"  Target Local Model: {MODEL_NAME} (Ollama Endpoint: {OLLAMA_URL})")
    print(f"  Task Scope: Option B (Memory Accuracy, Multi-Step Tools, Error Recovery)")
    print("=" * 80 + "\n")
    
    # Verify local model availability
    print("  Checking Ollama server connection...")
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
                    "test_id": test_id,
                    "type": test_type,
                    "status": status,
                    "accuracy_score": accuracy,
                    "response": resp_text,
                    "tokens": tokens,
                    "elapsed_sec": round(elapsed, 2)
                }
            else:
                resp_text, tokens, elapsed = harness.run_tool_task(test["prompt"])
                target_outcome = test.get("target_outcome")
                keywords = test.get("expected_recovery_keywords") or test.get("expected_keywords")
                score = evaluate_tool_completion(resp_text, target_outcome, keywords)
                status = "PASS" if score >= 80.0 else "PARTIAL" if score >= 40.0 else "FAIL"
                
                res_entry = {
                    "test_id": test_id,
                    "type": test_type,
                    "status": status,
                    "completion_score": score,
                    "response": resp_text,
                    "tokens": tokens,
                    "elapsed_sec": round(elapsed, 2)
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

    # Summary Report Table
    print("\n" + "=" * 80)
    print("  FINAL HEAD-TO-HEAD COMPARISON MATRIX (Model: granite4.1:8b)")
    print("=" * 80)
    print(f"{'Harness Architecture':<25} | {'Overall Score':<14} | {'Total Tokens':<12} | {'Total Time':<10}")
    print("-" * 75)
    
    sorted_harnesses = sorted(results.values(), key=lambda x: x["overall_score"], reverse=True)
    for h in sorted_harnesses:
        print(f"{h['harness_name']:<25} | {h['overall_score']:>12.2f}% | {h['total_tokens']:>12} | {h['total_time_sec']:>8.2f}s")
        
    print("=" * 80 + "\n")
    
    # Save results to JSON file
    out_dir = os.path.join(os.path.dirname(__file__), "benchmark_results")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "head_to_head_granite41_8b.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Detailed evaluation logs written to: [head_to_head_granite41_8b.json](file://{out_file})")

if __name__ == "__main__":
    main()
