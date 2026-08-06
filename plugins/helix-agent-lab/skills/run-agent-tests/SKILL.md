---
name: run-agent-tests
description: Run a user-requested Helix benchmark or deterministic prompt-case evaluation through installed coding-agent CLIs and report reproducible results.
---

# Run agent tests

Use this workflow only when the user asks to test or compare coding agents.

1. Call `inspect_environment` for the selected project.
2. State which agents and suite will run. Explain that prompts or code context may be sent to the chosen provider.
3. Prefer `auth_mode="account"`. It uses the official CLI's cached login and removes API-key environment variables from the child process. Never ask for credentials.
4. Use `start_helix_benchmark` for a Helix-AGI checkout containing `scripts/cross_agent_benchmark.py`.
5. Use `start_prompt_eval` for user-authored JSON/JSONL prompt cases.
6. Poll `get_run` until the run reaches `passed`, `failed`, or `cancelled`.
7. Report the suite, agents, auth mode, pass/fail counts, artifact location, and important errors. Do not claim one agent is generally superior from a small or single-domain suite.

Important billing note: account mode avoids silently inheriting API keys, but it does not guarantee that a provider will charge nothing. Provider entitlements and current CLI billing rules still apply.

Never modify provider credential caches, export OAuth tokens, scrape authenticated web sessions, or call provider backends directly.
