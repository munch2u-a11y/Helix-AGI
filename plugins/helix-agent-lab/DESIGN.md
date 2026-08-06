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
| OpenAI | Launch `codex exec` with cached ChatGPT login; strip `CODEX_API_KEY` and `OPENAI_API_KEY` in account mode | Codex is available through ChatGPT plans and consumes the plan's Codex allowance or credits. Limits vary by plan. |
| Anthropic | Launch official `claude -p`; strip `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` in account mode | Anthropic's planned June 15, 2026 Agent SDK billing change was paused. For now, `claude -p` and third-party app usage still draw from Claude subscription limits. |
| Google | Launch official `gemini` in headless mode with cached Google login; strip API-key/Vertex variables in account mode | Google-account or Google AI subscription quotas apply. API-key and Vertex routes remain separate pay-as-you-go options. |

Provider policies change independently of this plugin. The statements above were verified on 2026-08-06 against [OpenAI's Codex plan guide](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan), [Claude Code setup](https://docs.anthropic.com/en/docs/claude-code/getting-started), [Anthropic's paused Agent SDK change](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan), [Gemini CLI authentication](https://geminicli.com/docs/get-started/authentication/), and [Gemini quotas and pricing](https://geminicli.com/docs/resources/quota-and-pricing/).

Account mode is a billing-safety control, not a no-cost guarantee. A run can consume subscription allowance, provider credits, or configured overage capacity. Users should review the usage settings in each first-party product before running a large suite.

## Why token routing is rejected

- Consumer OAuth tokens are credentials, not a portable API entitlement.
- Extracting or relaying them expands the attack surface and creates refresh/revocation complexity.
- Google explicitly warns that third-party piggybacking on Gemini CLI OAuth is not supported.
- Provider subscription rules can change without a corresponding plugin release.
- OpenAI's cached auth file contains access tokens and is documented as password-equivalent.

Invoking the official CLI preserves the first-party authentication boundary without turning subscription credentials into a general API. The plugin should never inspect credential files, relay OAuth tokens, or imitate a first-party client.

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
