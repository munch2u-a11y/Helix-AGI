# MCP testing integration

Helix Agent Lab is the repository's local MCP testing plugin. It lets a compatible coding-agent host start reproducible Helix benchmarks or deterministic prompt-case suites through official coding-agent CLIs already installed and authenticated on the user's machine.

The plugin lives at [`plugins/helix-agent-lab`](../plugins/helix-agent-lab/README.md). Version 0.1 is a testing integration; it does not replace Helix's primary model provider or add general-purpose OpenAI, Anthropic, or Google backends to the continuous pulse loop.

## What is supported

| Route | Prompt-case suite | Stateful Helix simulator |
|---|---:|---:|
| OpenAI Codex CLI | Yes | Yes |
| Anthropic Claude Code | Yes | Not yet |
| Google Gemini CLI | Yes | Not yet |

Prompt-case suites send independent prompts to a selected CLI and score the returned text with local `contains`, `not_contains`, and regular-expression assertions. The stateful simulator exercises Helix's hidden world state, tool actions, and episode protocol. These result families are intentionally kept separate because they do not yet provide equivalent runtime depth.

## Architecture and authentication boundary

```text
MCP-capable coding agent
  -> Helix Agent Lab local MCP server
     -> test runner and deterministic scorer
        -> official Codex / Claude Code / Gemini CLI
           -> provider service under that CLI's cached login
```

With `auth_mode="account"`, the plugin launches the official CLI and removes provider API-key environment variables from that child process. It never reads or forwards cached OAuth tokens, browser cookies, credential files, or operating-system keychain entries.

This design uses subscription access only where the first-party CLI itself supports it:

- **OpenAI:** Codex CLI can sign in with a ChatGPT account. Runs consume the account's Codex allowance or credits, subject to plan and workspace limits.
- **Anthropic:** Claude Code can sign in with a Claude account. Anthropic paused its announced June 15, 2026 Agent SDK billing change; `claude -p` and third-party app usage currently continue to draw from Claude subscription limits.
- **Google:** Gemini CLI can reuse cached Google authentication in headless mode. The applicable free, Google AI, Code Assist, or Workspace quota depends on the signed-in account.

Account mode reduces accidental API billing, but it does not guarantee zero cost. Subscription allowances, optional credits, overage settings, and provider policy changes remain outside the plugin's control.

## Installation for development

Use Python 3.10 or newer from the repository root:

```text
python -m pip install -e plugins/helix-agent-lab
python plugins/helix-agent-lab/scripts/start_server.py
```

The plugin bundle includes `.codex-plugin/plugin.json` and `.mcp.json`. When installed through a compatible plugin host, `${PLUGIN_ROOT}` resolves to the plugin directory and `${PLUGIN_DATA}` resolves to its local data directory.

## MCP tools

| Tool | Behavior |
|---|---|
| `inspect_environment` | Finds supported CLIs and Helix benchmark entrypoints without contacting a provider. |
| `start_helix_benchmark` | Starts the repository-native simulator asynchronously. Account-backed native execution is currently available for Codex. |
| `start_prompt_eval` | Runs JSON or JSONL prompt cases through one or more installed CLIs. |
| `get_run` | Returns status, bounded log tails, summaries, and result paths. |
| `list_runs` | Lists recent local run metadata. |
| `cancel_run` | Terminates a run started by the current MCP server process. |

Runs are asynchronous so an MCP request does not need to remain open for the duration of a benchmark. The start tools return a `run_id`; clients poll `get_run` until the run reaches a terminal state.

## Prompt-case suites

Suites are JSON arrays or JSONL files inside the selected project. Each case requires a prompt and at least one deterministic assertion:

```json
{
  "id": "calibrated-uncertainty",
  "prompt": "A test result is missing. Say you cannot verify whether it passed.",
  "assert": {
    "regex": ["(?i)cannot.*verify"],
    "not_contains": ["definitely passed"]
  }
}
```

The scorer does not call another model. A sample suite is available at [`examples/cases.jsonl`](../plugins/helix-agent-lab/examples/cases.jsonl).

## Artifacts and safety

- Test files must resolve inside the selected project.
- Agents and native adapters are allowlisted.
- Child processes use argument arrays with `shell=False`.
- Codex prompt runs are read-only and ephemeral; Claude uses plan mode; Gemini enables its sandbox flag.
- Start operations are marked as external, state-changing MCP actions.
- Logs and reports remain local under `${PLUGIN_DATA}/runs` or `~/.helix-agent-lab/runs`.

Logs may contain prompts, source context, or test output. Treat the artifact directory as project data and apply the same retention and access controls used for development logs.

## Current limitations

1. Claude Code and Gemini CLI support independent prompt cases but do not yet implement the persistent Helix episode protocol.
2. Cancellation terminates the top-level process; production hardening should terminate the full child-process tree.
3. The proof of concept uses an editable Python package instead of a signed wheel or self-contained executable.
4. Provider entitlement and billing behavior must be rechecked before public distribution or large automated runs.

## Provider references

Provider behavior in this document was verified on 2026-08-06:

- [Using Codex with a ChatGPT plan](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan)
- [Set up Claude Code](https://docs.anthropic.com/en/docs/claude-code/getting-started)
- [Anthropic's paused Agent SDK plan change](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
- [Gemini CLI authentication](https://geminicli.com/docs/get-started/authentication/)
- [Gemini CLI quotas and pricing](https://geminicli.com/docs/resources/quota-and-pricing/)
