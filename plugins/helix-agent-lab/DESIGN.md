# Helix Agent Lab — design

## Recommendation

Ship v0.1 as a local/repository MCP plugin that orchestrates official installed CLIs. Do not build an OAuth token router and do not proxy provider APIs under a user's consumer login.

```text
Coding-agent host
  -> local MCP server
     -> test orchestrator and deterministic scorer
        -> official Codex / Claude Code / Gemini CLI
           -> provider service under that CLI's own authentication rules
```

The authentication boundary stays inside each first-party CLI. Helix Agent Lab owns only test inputs, process lifecycle, deterministic scoring, and local reports.

## MCP surface

| Tool | Purpose | Safety |
|---|---|---|
| `inspect_environment` | Discover installed CLIs and Helix entrypoints | Read-only, no provider contact |
| `start_helix_benchmark` | Run Helix's native hidden-state simulator | Local writes + provider network |
| `start_prompt_eval` | Run user-authored cases through official CLIs | Local writes + provider network |
| `get_run` | Read status and bounded log tails | Read-only |
| `list_runs` | List recent run metadata | Read-only |
| `cancel_run` | Terminate a run | Destructive annotation |

Runs are asynchronous because realistic agent evaluations regularly exceed normal MCP tool timeouts.

## Authentication and cost matrix

| Route | Supported design | Cost expectation |
|---|---|---|
| OpenAI | Launch `codex exec` with cached ChatGPT login; strip `CODEX_API_KEY` and `OPENAI_API_KEY` in account mode | Codex documents subscription access and reuse of saved CLI authentication. Subject to plan limits. |
| Anthropic | Launch official `claude -p`; strip `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` in account mode | Since June 15, 2026, `claude -p` uses Agent SDK monthly credit rather than normal interactive subscription limits; charges can occur after applicable credit. Do not promise zero cost. |
| Google | Launch official `gemini` in headless mode with cached Google login; strip API-key/Vertex variables in account mode | Google-account quotas apply. Do not extract or reuse Gemini OAuth credentials outside Gemini CLI. |

Sources: [OpenAI Codex authentication](https://learn.chatgpt.com/docs/auth), [OpenAI non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode), [Claude Code setup](https://docs.anthropic.com/en/docs/claude-code/getting-started), [Claude Agent SDK plan credit](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan), [Gemini CLI authentication](https://geminicli.com/docs/get-started/authentication/), and [Gemini quotas](https://geminicli.com/docs/resources/quota-and-pricing/).

## Why token routing is rejected

- Consumer OAuth tokens are credentials, not a portable API entitlement.
- Extracting or relaying them expands the attack surface and creates refresh/revocation complexity.
- Google explicitly warns that third-party piggybacking on Gemini CLI OAuth is not supported.
- Anthropic distinguishes ordinary native Claude Code use from third-party traffic routed against subscription limits.
- OpenAI's cached auth file contains access tokens and is documented as password-equivalent.

Invoking the official CLI is the narrow, supportable path. The plugin should never inspect credential files or imitate a first-party client.

## Helix integration

Helix already provides the hard parts of a credible benchmark:

- Hidden simulator state and executable tool calls.
- Deterministic scoring instead of essay grading.
- Runtime capability descriptors.
- Repeated runs, confidence intervals, efficiency measures, and trace artifacts.

The plugin calls `scripts/cross_agent_benchmark.py` rather than copying Helix code. That process boundary avoids a coupled fork and keeps the standalone plugin clean-room. If code is copied from or merged into Helix, its AGPL-3.0-or-later obligations must be handled separately.

## Full parity milestone

Helix's native simulator currently maps Codex to a persistent `exec/resume` wrapper. Hermes and Pi are Gemini API-key paths, not first-party Gemini subscription paths; there is no equivalent Claude Code runtime in `AVAILABLE_AGENTS`.

For full parity, add upstream runtime adapters that implement the same episode protocol:

1. `ClaudeCodePersistentRuntime`: `claude -p --output-format stream-json`, stable session ID, bounded turns, explicit permission mode.
2. `GeminiCliPersistentRuntime`: `gemini --output-format stream-json`, sandbox enabled, project-scoped session resume.
3. Shared observation/action schemas and identical seed delivery.
4. Capability metadata and billing/auth provenance in every report.

Do not label prompt-case results and full Helix-stateful results on one undifferentiated leaderboard.

## Production hardening

Before a public release:

1. Replace Python bootstrap friction with signed wheels or a self-contained executable.
2. Add process-tree cancellation and crash recovery after MCP server restart.
3. Add configurable log retention and secret-pattern redaction.
4. Pin dependencies and publish an SBOM.
5. Add Windows, macOS, and Linux integration tests with mocked first-party CLIs.
6. Add signed run manifests containing suite digest, repository commit, CLI versions, auth mode, seed, timestamps, and scorer version.
7. Seek provider and plugin-directory review before presenting cross-vendor adapters as a public universal plugin.
