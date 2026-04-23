"""
Helix_main — Gemini Client

The API gateway for ALL Helix cognition. In V3-API, Gemini IS
the thinking mind (3.0 Pro for consciousness) AND the workforce
(2.5 Flash for sub-agents, tools, synthesis).
"""

import os
import json
import time
from pathlib import Path
from datetime import datetime, date
from typing import Optional

from google import genai
from google.genai import types

import logging

logger = logging.getLogger("helix.gemini")

# Approximate pricing per 1M tokens (USD)
PRICING = {
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-3.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-3-flash-preview": {"input": 0.10, "output": 0.40},
    "gemini-2.5-pro-preview-05-06": {"input": 1.25, "output": 10.00},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-3-pro-preview": {"input": 1.25, "output": 10.00},
    "gemini-3.1-pro-preview": {"input": 1.25, "output": 10.00},
}
DEFAULT_PRICING = {"input": 0.50, "output": 2.00}


class GeminiClient:
    """Gemini API wrapper for ALL Helix cognition.

    V4.1: Gemini powers everything:
    - Consciousness (Gemini 3 Flash) — the thinking mind
    - Sub-agents (Gemini 3 Flash) — keeper, librarian, classification
    - Deep Thought (Gemini 3 Flash) — complex analysis
    """

    def __init__(self, config: dict, base_dir: Path):
        self.full_config = config
        self.config = config.get("gemini", {})
        self.base_dir = base_dir
        self.cost_file = base_dir / "logs" / "cost_tracker.json"

        self.conscious_model = self.config.get("conscious_model", "gemini-2.5-flash")
        self.default_model = self.config.get("default_model", "gemini-2.5-flash")
        self.heavy_model = self.config.get("heavy_model", "gemini-2.5-flash")

        self.daily_limit = self.config.get("daily_cost_limit_usd", 2.00)
        self.monthly_limit = self.config.get("monthly_cost_limit_usd", 50.00)

        # Per-provider limits (Anthropic may have its own budget)
        self._provider_limits = {
            "gemini": {
                "daily": self.daily_limit,
                "monthly": self.monthly_limit,
            },
            "anthropic": {
                "daily": config.get("anthropic", {}).get("daily_cost_limit_usd", self.daily_limit),
                "monthly": config.get("anthropic", {}).get("monthly_cost_limit_usd", self.monthly_limit),
            },
        }

        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            api_key = self.full_config.get("gemini_api_key", "")
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY environment variable or config key not set. "
                "Set it with: export GEMINI_API_KEY='your-key-here'"
            )
        self.client = genai.Client(api_key=api_key)

        self.cost_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.cost_file.exists():
            self._write_cost_data({"calls": [], "daily_totals": {}, "monthly_totals": {}})

    def _call_with_retry(self, func, *args, pro_fallback=False, **kwargs):
        """Invoke API function with retries on 503/UNAVAILABLE.
        Falls back to Flash model if Pro is unavailable.
        
        pro_fallback: If True, include 2.5-pro in the fallback chain.
                      Only consciousness should use this; sub-agents skip
                      Pro to preserve its quota for primary thinking.
        """
        max_retries = 3
        base_delay = 2

        original_model = kwargs.get("model")
        fallback_sequence = []
        default_flash = getattr(self, "default_model", "gemini-2.5-flash")
        
        if original_model == "gemini-3-flash-preview":
            if pro_fallback:
                fallback_sequence = ["gemini-2.5-pro", default_flash]
            else:
                fallback_sequence = [default_flash]
        elif original_model and "pro" in original_model.lower():
            fallback_sequence = [default_flash]
        elif original_model and original_model != default_flash:
            fallback_sequence = [default_flash]

        for attempt in range(max_retries):
            try:
                if attempt > 0 and fallback_sequence:
                    fallback_idx = min(attempt - 1, len(fallback_sequence) - 1)
                    current_fallback = fallback_sequence[fallback_idx]
                    
                    if kwargs.get("model") != current_fallback:
                        logger.warning(
                            f"Capacity issue with {original_model}. "
                            f"Dropping to fallback: {current_fallback} (attempt {attempt + 1}/{max_retries})"
                        )
                        kwargs["model"] = current_fallback

                return func(*args, **kwargs)

            except Exception as e:
                err_str = str(e).upper()
                is_retryable = any(
                    msg in err_str
                    for msg in ["503", "UNAVAILABLE", "HIGH DEMAND", "SERVICE UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "QUOTA"]
                )

                if is_retryable and attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        f"Gemini API Capacity/Quota Error ({kwargs.get('model', 'unknown')}). "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                    continue
                else:
                    raise

    def ask(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: str = "auto",
        temperature: float = 0.7,
    ) -> str:
        """Send a prompt to Gemini and return text response.

        Used by subconscious agents for synthesis, classification, analysis.
        """
        model_name = self._resolve_model(model)

        config = types.GenerateContentConfig(temperature=temperature)
        if system_prompt:
            config.system_instruction = system_prompt

        start_time = time.time()
        response = self._call_with_retry(
            self.client.models.generate_content,
            model=model_name,
            contents=prompt,
            config=config,
        )
        elapsed = time.time() - start_time

        usage = response.usage_metadata
        input_tokens = usage.prompt_token_count or 0
        output_tokens = usage.candidates_token_count or 0
        cost = self._compute_cost(model_name, input_tokens, output_tokens)

        self._log_call(
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            elapsed=elapsed,
            prompt_preview=prompt[:200],
        )

        return response.text

    def ask_with_tools(
        self,
        prompt: str,
        tools: list[dict],
        system_prompt: Optional[str] = None,
        model: str = "auto",
    ) -> dict:
        """Send prompt with tool definitions, return structured output.

        Used by Action Agent for single-round tool calls.
        """
        model_name = self._resolve_model(model)

        config = types.GenerateContentConfig(
            temperature=0.2,
            tools=tools,
        )
        if system_prompt:
            config.system_instruction = system_prompt

        start_time = time.time()
        response = self._call_with_retry(
            self.client.models.generate_content,
            model=model_name,
            contents=prompt,
            config=config,
        )
        elapsed = time.time() - start_time

        usage = response.usage_metadata
        input_tokens = usage.prompt_token_count or 0
        output_tokens = usage.candidates_token_count or 0
        cost = self._compute_cost(model_name, input_tokens, output_tokens)

        self._log_call(
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            elapsed=elapsed,
            prompt_preview=prompt[:200],
        )

        result = {"text": None, "tool_calls": []}

        if response.candidates:
            for part in response.candidates[0].content.parts:
                if part.text:
                    result["text"] = part.text
                if part.function_call:
                    result["tool_calls"].append({
                        "name": part.function_call.name,
                        "args": dict(part.function_call.args) if part.function_call.args else {},
                    })

        return result

    def ask_with_tools_loop(
        self,
        prompt: str,
        tools: list[dict],
        tool_executor,
        system_prompt: Optional[str] = None,
        model: str = "auto",
        max_rounds: int = 5,
        loop_cost_cap: float = 0.50,
    ) -> dict:
        """Multi-round tool calling loop.

        The core mechanism for the Action Agent — sends prompt to Gemini,
        model calls tools, we execute them, send results back, repeat
        until the model responds with text or max rounds reached.

        Circuit breaker: exits early on 2+ consecutive rounds with tool
        failures, or when accumulated loop cost exceeds loop_cost_cap.

        All calls and results are fully logged — no truncation.
        """
        model_name = self._resolve_model(model)
        all_tool_calls = []
        all_tool_results = []
        accumulated_cost = 0.0
        consecutive_failures = 0

        config = types.GenerateContentConfig(
            temperature=0.7,
            tools=tools,
        )
        if system_prompt:
            config.system_instruction = system_prompt

        # Initial request
        start_time = time.time()
        response = self._call_with_retry(
            self.client.models.generate_content,
            model=model_name,
            contents=prompt,
            config=config,
        )
        elapsed = time.time() - start_time

        usage = response.usage_metadata
        input_tokens = usage.prompt_token_count or 0
        output_tokens = usage.candidates_token_count or 0
        cost = self._compute_cost(model_name, input_tokens, output_tokens)
        accumulated_cost += cost
        self._log_call(
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            elapsed=elapsed,
            prompt_preview=prompt[:200],
        )

        # Multi-round loop
        circuit_broken = False
        for round_num in range(max_rounds):
            if not response.candidates:
                break

            content = response.candidates[0].content
            parts = content.parts if content else None
            if not parts:
                break

            tool_calls_this_round = [
                p for p in parts
                if hasattr(p, "function_call") and p.function_call and p.function_call.name
            ]

            if not tool_calls_this_round:
                break  # Model responded with text — done

            # Execute each tool call
            function_responses = []
            round_had_failure = False
            for part in tool_calls_this_round:
                fc = part.function_call
                args = dict(fc.args) if fc.args else {}
                logger.info(f"Tool call round {round_num + 1}: {fc.name}({args})")

                try:
                    result_str = tool_executor(fc.name, args)
                except Exception as e:
                    result_str = f"Tool error: {e}"

                # Track failures for circuit breaker
                if isinstance(result_str, str) and result_str.startswith("Tool error:"):
                    round_had_failure = True
                else:
                    consecutive_failures = 0  # Reset on any success

                all_tool_calls.append({"name": fc.name, "args": args})
                all_tool_results.append({"name": fc.name, "result": result_str})

                function_responses.append(
                    types.Part.from_function_response(
                        name=fc.name,
                        response={"result": result_str},
                    )
                )

            # Circuit breaker: consecutive round failures
            if round_had_failure:
                consecutive_failures += 1
                if consecutive_failures >= 2:
                    logger.warning(
                        f"Circuit breaker tripped: {consecutive_failures} consecutive "
                        f"rounds with tool failures. Exiting tool loop early."
                    )
                    circuit_broken = True
                    break

            # Circuit breaker: cost cap
            if accumulated_cost >= loop_cost_cap:
                logger.warning(
                    f"Tool loop cost cap reached: ${accumulated_cost:.4f} >= "
                    f"${loop_cost_cap:.2f}. Exiting early."
                )
                circuit_broken = True
                break

            # Send tool results back to model
            model_content = response.candidates[0].content
            start_time = time.time()
            response = self._call_with_retry(
                self.client.models.generate_content,
                model=model_name,
                contents=[
                    types.Content(role="user", parts=[types.Part.from_text(text=prompt)]),
                    model_content,
                    types.Content(role="user", parts=function_responses),
                ],
                config=config,
            )
            elapsed = time.time() - start_time

            usage = response.usage_metadata
            in_t = usage.prompt_token_count or 0
            out_t = usage.candidates_token_count or 0
            c = self._compute_cost(model_name, in_t, out_t)
            accumulated_cost += c
            self._log_call(
                model=model_name,
                input_tokens=in_t,
                output_tokens=out_t,
                cost=c,
                elapsed=elapsed,
                prompt_preview=f"tool_round_{round_num + 1}",
            )

        # Extract final text — full content, no truncation
        final_text = ""
        if circuit_broken:
            final_text = (
                f"[Tool loop terminated: "
                f"{'consecutive failures' if consecutive_failures >= 2 else 'cost cap exceeded'} "
                f"after {len(all_tool_calls)} tool calls, ${accumulated_cost:.4f} spent]"
            )
        elif response.candidates:
            final_content = response.candidates[0].content
            final_parts = final_content.parts if final_content else None
            if final_parts:
                for part in final_parts:
                    if hasattr(part, "text") and part.text:
                        final_text += part.text

        return {
            "text": final_text,
            "tool_calls": all_tool_calls,
            "tool_results": all_tool_results,
            "circuit_broken": circuit_broken,
            "loop_cost": round(accumulated_cost, 6),
        }

    # -- Cost tracking --

    def get_daily_cost(self, provider: str = None) -> float:
        data = self._read_cost_data()
        today = date.today().isoformat()
        daily = data.get("daily_totals", {})
        if provider:
            return daily.get(f"{today}:{provider}", 0.0)
        # Sum across all providers for the day
        total = 0.0
        for key, val in daily.items():
            if key.startswith(today):
                total += val
        return total

    def get_monthly_cost(self, provider: str = None) -> float:
        data = self._read_cost_data()
        month = date.today().strftime("%Y-%m")
        monthly = data.get("monthly_totals", {})
        if provider:
            return monthly.get(f"{month}:{provider}", 0.0)
        # Sum across all providers for the month
        total = 0.0
        for key, val in monthly.items():
            if key.startswith(month):
                total += val
        return total

    def is_within_budget(self, provider: str = None) -> bool:
        if provider:
            limits = self._provider_limits.get(provider, self._provider_limits["gemini"])
            return (
                self.get_daily_cost(provider) < limits["daily"]
                and self.get_monthly_cost(provider) < limits["monthly"]
            )
        # Check all providers
        for prov, limits in self._provider_limits.items():
            if self.get_daily_cost(prov) >= limits["daily"]:
                return False
            if self.get_monthly_cost(prov) >= limits["monthly"]:
                return False
        return True

    def get_cost_report(self) -> dict:
        report = {
            "within_budget": self.is_within_budget(),
            "providers": {},
        }
        for prov, limits in self._provider_limits.items():
            daily = self.get_daily_cost(prov)
            monthly = self.get_monthly_cost(prov)
            report["providers"][prov] = {
                "daily_cost": round(daily, 6),
                "daily_limit": limits["daily"],
                "daily_remaining": round(limits["daily"] - daily, 6),
                "monthly_cost": round(monthly, 6),
                "monthly_limit": limits["monthly"],
                "monthly_remaining": round(limits["monthly"] - monthly, 6),
            }
        # Legacy top-level fields for backward compatibility
        report["daily_cost"] = round(self.get_daily_cost(), 6)
        report["monthly_cost"] = round(self.get_monthly_cost(), 6)
        return report

    # -- Private --

    def _resolve_model(self, model: str) -> str:
        if model in ("auto", "default"):
            return self.default_model
        elif model == "conscious":
            return self.conscious_model
        elif model == "heavy":
            return self.heavy_model
        return model

    def _compute_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        pricing = PRICING.get(model, DEFAULT_PRICING)
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    def _log_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        elapsed: float,
        prompt_preview: str,
        provider: str = "gemini",
    ):
        data = self._read_cost_data()
        today = date.today().isoformat()
        month = date.today().strftime("%Y-%m")

        call_record = {
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "provider": provider,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 8),
            "elapsed_seconds": round(elapsed, 2),
            "prompt_preview": prompt_preview,
        }
        data.setdefault("calls", []).append(call_record)

        # Prune call log to prevent unbounded growth
        if len(data["calls"]) > 200:
            data["calls"] = data["calls"][-200:]

        # Provider-keyed daily totals
        daily_key = f"{today}:{provider}"
        data.setdefault("daily_totals", {})
        data["daily_totals"][daily_key] = data["daily_totals"].get(daily_key, 0.0) + cost

        # Provider-keyed monthly totals
        monthly_key = f"{month}:{provider}"
        data.setdefault("monthly_totals", {})
        data["monthly_totals"][monthly_key] = data["monthly_totals"].get(monthly_key, 0.0) + cost

        self._write_cost_data(data)

    def _read_cost_data(self) -> dict:
        try:
            with open(self.cost_file, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"calls": [], "daily_totals": {}, "monthly_totals": {}}

    def _write_cost_data(self, data: dict):
        with open(self.cost_file, "w") as f:
            json.dump(data, f, indent=2)
