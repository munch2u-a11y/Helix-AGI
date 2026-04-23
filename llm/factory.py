from pathlib import Path
from llm.providers.gemini_provider import GeminiConsciousProvider
from llm.providers.anthropic_provider import AnthropicConsciousProvider
from llm.providers.openai_provider import OpenAIConsciousProvider

def get_conscious_provider(config: dict, base_dir: Path, cost_tracker) -> 'ConsciousProvider':
    provider_name = config.get("conscious_provider", "gemini").lower()
    
    if provider_name == "anthropic":
        return AnthropicConsciousProvider(config, base_dir, cost_tracker)
    elif provider_name == "openai":
        return OpenAIConsciousProvider(config, base_dir, cost_tracker)
    else:
        return GeminiConsciousProvider(config, base_dir, cost_tracker)
