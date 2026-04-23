import time
import logging
from google.genai import types
from llm.base import ConsciousProvider

logger = logging.getLogger("helix.gemini_provider")

class GeminiConsciousProvider(ConsciousProvider):
    def think(self, user_message, system_prompt, tools, tool_runner, emit_callback, heartbeat_count, hyperfocus=False):
        self.chat_history.append(types.Content(role="user", parts=[types.Part.from_text(text=user_message)]))
        
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.8,
            max_output_tokens=8192,
            tools=[types.Tool(function_declarations=tools)] if tools else None
        )
        
        gemini_config = self.config.get("gemini", {})
        model_name = "gemini-3.1-pro-preview" if hyperfocus else gemini_config.get("conscious_model", "gemini-3-flash-preview")
        
        start_time = time.time()
        response = self._cost_tracker._call_with_retry(
            self._cost_tracker.client.models.generate_content,
            pro_fallback=True,
            model=model_name,
            contents=list(self.chat_history),
            config=config,
        )
        elapsed = time.time() - start_time
        
        usage = response.usage_metadata
        in_t = usage.prompt_token_count or 0
        out_t = usage.candidates_token_count or 0
        cost = self._cost_tracker._compute_cost(model_name, in_t, out_t)
        self.log_cost(model_name, in_t, out_t, cost, elapsed, f"heartbeat_{heartbeat_count}", "gemini")
        
        if not response.candidates:
            return ""
        
        content = response.candidates[0].content
        parts = content.parts if content else []
        text_parts = [p.text for p in parts if hasattr(p, 'text') and p.text]
        fc_parts = [p for p in parts if hasattr(p, 'function_call') and p.function_call and p.function_call.name]
        
        result_text = "\n".join(text_parts)
        
        if fc_parts:
            tool_result_text = self._execute_tool_calls(fc_parts, content, config, model_name, tool_runner, emit_callback, heartbeat_count)
            if tool_result_text:
                result_text = (result_text + "\n" + tool_result_text).strip()
                
        if result_text:
            self.chat_history.append(types.Content(role="model", parts=[types.Part.from_text(text=result_text)]))
            if len(self.chat_history) > 30:
                self.chat_history = self.chat_history[:2] + self.chat_history[-20:]
                
        return result_text

    def _execute_tool_calls(self, function_call_parts, model_content, config, base_model_name, tool_runner, emit_callback, heartbeat_count):
        accumulated_text = []
        current_fc_parts = function_call_parts
        running_contents = list(self.chat_history)
        
        for pulse_num in range(self.SEQUENTIAL_CHAIN_LIMIT):
            fr_parts = []
            for part in current_fc_parts:
                fc = part.function_call
                args = dict(fc.args) if fc.args else {}
                logger.info(f"Tool call [pulse {pulse_num + 1}]: {fc.name}({args})")
                res = f"Tool {fc.name} not available"
                if tool_runner:
                    try: res = tool_runner.execute(fc.name, args)
                    except Exception as e: res = f"Tool error: {e}"
                emit_callback(fc.name, res, args)
                fr_parts.append(types.Part.from_function_response(name=fc.name, response={"result": str(res)}))
                
            running_contents.append(model_content)
            running_contents.append(types.Content(role="user", parts=fr_parts))
            
            start_time = time.time()
            follow_response = self._cost_tracker._call_with_retry(
                self._cost_tracker.client.models.generate_content,
                pro_fallback=True, model=base_model_name, contents=running_contents, config=config
            )
            elapsed = time.time() - start_time
            
            u = follow_response.usage_metadata
            i_t = u.prompt_token_count or 0
            o_t = u.candidates_token_count or 0
            c = self._cost_tracker._compute_cost(base_model_name, i_t, o_t)
            self.log_cost(base_model_name, i_t, o_t, c, elapsed, f"tool_chain_{heartbeat_count}_pulse_{pulse_num + 1}", "gemini")
            
            if not follow_response.candidates: 
                break
            
            follow_content = follow_response.candidates[0].content
            follow_parts = follow_content.parts if follow_content else []
            new_text = [p.text for p in follow_parts if hasattr(p, 'text') and p.text]
            new_fc = [p for p in follow_parts if hasattr(p, 'function_call') and p.function_call and p.function_call.name]
            
            if new_text: 
                accumulated_text.append("\n".join(new_text))
            
            if new_fc:
                current_fc_parts = new_fc
                model_content = follow_content
                continue
            else:
                break
        
        return "\n".join(accumulated_text)
