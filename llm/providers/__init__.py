"""
Helix — LLM Provider Abstraction

Each provider is a separate module that implements the ChatSession interface.
Switching providers = changing one import + config. No other code changes.

Supported:
    ollama   — Local Ollama (Vulkan auto-offload, 128K context)
    llama_cpp — llama-cpp-python (when it supports the target model)

Future:
    gemini   — Google Gemini API
    anthropic — Anthropic Claude API
    openai   — OpenAI GPT API
"""
