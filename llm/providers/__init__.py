"""
Helix — LLM Provider Abstraction

Each provider is a separate module that implements the ChatSession interface.
Switching providers = changing one import + config. No other code changes.

Supported:
    gemini    — Google Gemini API (default conscious mind)
    anthropic — Anthropic Claude API (set HELIX_PROVIDER=anthropic)
    ollama    — Local Ollama (Vulkan auto-offload, 128K context)
    llama_cpp — llama-cpp-python (when it supports the target model)
    codex_cli — Persistent Codex App Server authenticated through ChatGPT
    codex_subscription — Isolated ``codex exec`` benchmark transport

Future:
    openai    — OpenAI GPT API
"""
