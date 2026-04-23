import time
import logging
import json
from llm.base import ConsciousProvider
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

logger = logging.getLogger("helix.openai_provider")

class OpenAIConsciousProvider(ConsciousProvider):
    def __init__(self, config, base_dir, cost_tracker=None):
        super().__init__(config, base_dir, cost_tracker)
        if not OpenAI:
            raise ImportError("Please 'pip install openai' to use OpenAIConsciousProvider")
        self.client = OpenAI(api_key=config.get("openai_api_key", ""))

    def _convert_tools(self, full_tools):
        if not full_tools: return []
        openai_tools = []
        for td in full_tools:
            props = getattr(td.parameters, 'properties', {})
            schema_props = {}
            for name, schema_obj in props.items():
                schema_props[name] = {
                    "type": getattr(schema_obj, 'type', 'string').lower(),
                    "description": getattr(schema_obj, 'description', "")
                }
            req = getattr(td.parameters, 'required', [])
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": td.name,
                    "description": td.description,
                    "parameters": {
                        "type": "object",
                        "properties": schema_props,
                        "required": req if req else []
                    }
                }
            })
        return openai_tools

    def think(self, user_message, system_prompt, tools, tool_runner, emit_callback, heartbeat_count, hyperfocus=False):
        self.chat_history.append({"role": "user", "content": user_message})
        
        openai_config = self.config.get("openai", {})
        model_name = "gpt-4o" if hyperfocus else openai_config.get("conscious_model", "gpt-4o")
        openai_tools = self._convert_tools(tools)
        
        messages = [{"role": "system", "content": system_prompt}] + self.chat_history
        
        start_time = time.time()
        try:
            kwargs = {
                "model": model_name,
                "messages": messages,
                "temperature": 0.8,
                "max_tokens": 8192
            }
            if openai_tools:
                kwargs["tools"] = openai_tools
            response = self.client.chat.completions.create(**kwargs)
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return ""
        elapsed = time.time() - start_time
        
        in_t = response.usage.prompt_tokens
        out_t = response.usage.completion_tokens
        cost = (in_t / 1_000_000) * 5.00 + (out_t / 1_000_000) * 15.00
        self.log_cost(model_name, in_t, out_t, cost, elapsed, f"heartbeat_{heartbeat_count}", "openai")
        
        choice = response.choices[0]
        msg = choice.message
        
        msg_dict = {"role": "assistant"}
        if msg.content: msg_dict["content"] = msg.content
        if msg.tool_calls:
            tool_calls_list = []
            for tc in msg.tool_calls:
                tool_calls_list.append({
                    "id": tc.id,
                    "type": tc.type,
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                })
            msg_dict["tool_calls"] = tool_calls_list
        self.chat_history.append(msg_dict)
        
        result_text = msg.content or ""
        
        if msg.tool_calls:
            tool_result_text = self._execute_tool_calls(
                msg.tool_calls, system_prompt, openai_tools, model_name, tool_runner, emit_callback, heartbeat_count
            )
            if tool_result_text:
                result_text = (result_text + "\n" + tool_result_text).strip()
                
        if len(self.chat_history) > 30:
            self.chat_history = self.chat_history[:2] + self.chat_history[-20:]
            
        return result_text

    def _execute_tool_calls(self, tool_calls, system_prompt, openai_tools, base_model_name, tool_runner, emit_callback, heartbeat_count):
        accumulated_text = []
        current_tool_calls = tool_calls
        
        for pulse_num in range(self.SEQUENTIAL_CHAIN_LIMIT):
            for tc in current_tool_calls:
                try: args = json.loads(tc.function.arguments)
                except: args = {}
                logger.info(f"Tool call [pulse {pulse_num + 1}]: {tc.function.name}({args})")
                res = f"Tool {tc.function.name} not available"
                if tool_runner:
                    try: 
                        res = tool_runner.execute(tc.function.name, args)
                    except Exception as e: 
                        res = f"Tool error: {e}"
                emit_callback(tc.function.name, res, args)
                self.chat_history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(res)
                })
                
            messages = [{"role": "system", "content": system_prompt}] + self.chat_history
            start_time = time.time()
            try:
                kwargs = {
                    "model": base_model_name,
                    "messages": messages,
                    "temperature": 0.8,
                    "max_tokens": 8192,
                    "tools": openai_tools
                }
                response = self.client.chat.completions.create(**kwargs)
            except Exception as e:
                logger.error(f"OpenAI tool chain API error: {e}")
                break
            elapsed = time.time() - start_time
            
            in_t = response.usage.prompt_tokens
            out_t = response.usage.completion_tokens
            cost = (in_t / 1_000_000) * 5.00 + (out_t / 1_000_000) * 15.00
            self.log_cost(base_model_name, in_t, out_t, cost, elapsed, f"tool_chain_{heartbeat_count}_pulse_{pulse_num + 1}", "openai")
            
            choice = response.choices[0]
            msg = choice.message
            msg_dict = {"role": "assistant"}
            if msg.content: msg_dict["content"] = msg.content
            if msg.tool_calls:
                tool_calls_list = []
                for tc in msg.tool_calls:
                    tool_calls_list.append({
                        "id": tc.id,
                        "type": tc.type,
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                    })
                msg_dict["tool_calls"] = tool_calls_list
            self.chat_history.append(msg_dict)
            
            if msg.content:
                accumulated_text.append(msg.content)
                
            if msg.tool_calls:
                current_tool_calls = msg.tool_calls
                continue
            else:
                break
                
        return "\n".join(accumulated_text)
