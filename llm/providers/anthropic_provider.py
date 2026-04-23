import time
import logging
from llm.base import ConsciousProvider
try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

logger = logging.getLogger("helix.anthropic_provider")

class AnthropicConsciousProvider(ConsciousProvider):
    def __init__(self, config, base_dir, cost_tracker=None):
        super().__init__(config, base_dir, cost_tracker)
        if not Anthropic:
            raise ImportError("Please 'pip install anthropic' to use AnthropicConsciousProvider")
        self.client = Anthropic(api_key=config.get("anthropic_api_key", ""))

    def _convert_tools(self, full_tools):
        if not full_tools: return []
        anthropic_tools = []
        for td in full_tools:
            props = getattr(td.parameters, 'properties', {})
            schema_props = {}
            for name, schema_obj in props.items():
                schema_props[name] = {
                    "type": getattr(schema_obj, 'type', 'string').lower(),
                    "description": getattr(schema_obj, 'description', "")
                }
            req = getattr(td.parameters, 'required', [])
            anthropic_tools.append({
                "name": td.name,
                "description": td.description,
                "input_schema": {
                    "type": "object",
                    "properties": schema_props,
                    "required": req if req else []
                }
            })
        return anthropic_tools

    def think(self, user_message, system_prompt, tools, tool_runner, emit_callback, heartbeat_count, hyperfocus=False):
        self.chat_history.append({"role": "user", "content": user_message})
        
        anthropic_config = self.config.get("anthropic", {})
        model_name = "claude-3-7-sonnet-20250219" if hyperfocus else anthropic_config.get("conscious_model", "claude-3-7-sonnet-20250219")
        anthropic_tools = self._convert_tools(tools)
        
        start_time = time.time()
        try:
            response = self.client.messages.create(
                model=model_name,
                max_tokens=8192,
                temperature=0.8,
                system=system_prompt,
                messages=self.chat_history,
                tools=anthropic_tools
            )
        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            return ""
        elapsed = time.time() - start_time
        
        in_t = response.usage.input_tokens
        out_t = response.usage.output_tokens
        
        cost = (in_t / 1_000_000) * 3.00 + (out_t / 1_000_000) * 15.00
        self.log_cost(model_name, in_t, out_t, cost, elapsed, f"heartbeat_{heartbeat_count}", "anthropic")
        
        if response.stop_reason == "max_tokens":
            logger.warning("Anthropic max_tokens reached")
            
        self.chat_history.append({"role": "assistant", "content": response.content})
        
        text_parts = [block.text for block in response.content if block.type == "text"]
        tool_calls = [block for block in response.content if block.type == "tool_use"]
        
        result_text = "\n".join(text_parts)
        
        if tool_calls:
            tool_result_text = self._execute_tool_calls(
                tool_calls, system_prompt, anthropic_tools, model_name, tool_runner, emit_callback, heartbeat_count
            )
            if tool_result_text:
                result_text = (result_text + "\n" + tool_result_text).strip()
                
        if len(self.chat_history) > 30:
            self.chat_history = self.chat_history[:2] + self.chat_history[-20:]
            
        return result_text

    def _execute_tool_calls(self, tool_use_blocks, system_prompt, anthropic_tools, base_model_name, tool_runner, emit_callback, heartbeat_count):
        accumulated_text = []
        current_tool_calls = tool_use_blocks
        
        for pulse_num in range(self.SEQUENTIAL_CHAIN_LIMIT):
            tool_results = []
            for block in current_tool_calls:
                args = block.input
                logger.info(f"Tool call [pulse {pulse_num + 1}]: {block.name}({args})")
                res = f"Tool {block.name} not available"
                if tool_runner:
                    try: 
                        res = tool_runner.execute(block.name, args)
                    except Exception as e: 
                        res = f"Tool error: {e}"
                emit_callback(block.name, res, args)
                
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(res)
                })
                
            self.chat_history.append({"role": "user", "content": tool_results})
            
            start_time = time.time()
            try:
                response = self.client.messages.create(
                    model=base_model_name,
                    max_tokens=8192,
                    temperature=0.8,
                    system=system_prompt,
                    messages=self.chat_history,
                    tools=anthropic_tools
                )
            except Exception as e:
                logger.error(f"Anthropic tool chain API error: {e}")
                break
            elapsed = time.time() - start_time
            
            in_t = response.usage.input_tokens
            out_t = response.usage.output_tokens
            c = (in_t / 1_000_000) * 3.00 + (out_t / 1_000_000) * 15.00
            self.log_cost(base_model_name, input_tokens=in_t, output_tokens=out_t, cost=c, elapsed=elapsed, prompt_preview=f"tool_chain_{heartbeat_count}_pulse_{pulse_num + 1}", provider="anthropic")
            
            self.chat_history.append({"role": "assistant", "content": response.content})
            
            new_text = [block.text for block in response.content if block.type == "text"]
            new_fc = [block for block in response.content if block.type == "tool_use"]
            
            if new_text:
                accumulated_text.append("\n".join(new_text))
                
            if new_fc:
                current_tool_calls = new_fc
                continue
            else:
                break
                
        return "\n".join(accumulated_text)
