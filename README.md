# Avos-CLI

**Portable memory for codebases, AI agents, and engineering teams.**

Avos adds a memory layer on top of your repository so AI agents and humans can understand **what changed**, **why it changed**, and **how it was built** — before they modify existing code.

```
connect -> ingest -> ask / history -> session-start -> code -> session-end
```

Works with **Claude Code**, **Cursor**, and the **terminal**. Python 3.10+. Apache-2.0.

---

## Why Avos-CLI exists

AI coding agents can read the current file tree, but that is not the same as knowing:

- why a function exists
- what constraints shaped a module
- which old assumptions still matter
- what happened in previous PRs
- how a feature was implemented across a session

That gap causes bad rewrites, repeated mistakes, and fragile changes.

Avos fixes it by attaching **portable memory** to a repository — two memory planes that persist across agents, sessions, and contributors.

---

## Two memory planes

### Repository Memory (long-term)

Stores the durable history of the codebase: PRs, commits, issues, comments, and documentation.

Powers `avos ask` and `avos history`.

### Session Memory (implementation trail)

Stores the working context of each coding session: goal, files touched, decisions, errors, tests run, and remaining risks.

Powers `avos session-start`, `avos session-end`, and `avos session-ask`.

Together, these let you understand both the **history of the repository** and the **audit trail of how a change was built**.

---

## Quick start

### 1. Install

```bash
pip install avos-cli
```

### 2. Set environment variables

```bash
export AVOS_API_KEY="your-avos-api-key"
export GITHUB_TOKEN="your-github-token"

# For LLM synthesis (ask / history)
export ANTHROPIC_API_KEY="your-key"   # or OPENAI_API_KEY

# Optional: for --json output formatting
export REPLY_MODEL="your-model-id"
export REPLY_MODEL_URL="https://api.example.com/v1/chat/completions"
export REPLY_MODEL_API_KEY="your-reply-model-key"
```

### 3. Connect and ingest

```bash
avos connect org/repo
avos ingest org/repo --since 90d
```

### 4. Ask a question

```bash
avos ask "Why does the auth module use JWT instead of sessions?"
```

### 5. Review history before editing

```bash
avos history "payment retry logic"
```

### 6. Track a coding session

```bash
avos session-start "Fix retry backoff in payment worker"
# ... do work ...
avos session-end
```

---

## Command reference

| Command                                                 | What it does                                                    |
| ------------------------------------------------------- | --------------------------------------------------------------- |
| `avos connect org/repo`                                 | Attach a repository to Avos Memory                              |
| `avos ingest org/repo --since 90d`                      | Import PRs, issues, commits, and docs into repository memory    |
| `avos ingest-pr org/repo 123`                           | Ingest a single PR (after push/merge)                           |
| `avos ask "question"`                                   | Search repository memory for evidence-backed answers            |
| `avos history "subject"`                                | Reconstruct the chronological history of a subsystem or concept |
| `avos session-start "goal"`                             | Start a tracked coding session                                  |
| `avos session-end`                                      | End the session and store the implementation trail              |
| `avos session-status`                                   | Check if a session is currently active                          |
| `avos session-ask "question"`                           | Search session memory for implementation context                |
| `avos worktree-add <path> <branch> "goal" --agent name` | Create a git worktree with auto session start                   |
| `avos worktree-init`                                    | Initialize avos in an existing git worktree                     |
| `avos hook-install`                                     | Install pre-push hook for automatic commit sync                 |

### Global options

```
--json      Emit machine-readable JSON (for AI agents and automation)
--verbose   Enable debug output
--version   Show version
```

---

## JSON output for AI agents

Every command supports `--json` for strict machine-readable output:

```bash
avos --json session-status
avos --json ask "how does auth work?"
avos --json ingest-pr org/repo 123
```

All JSON responses follow the same envelope:

```json
{
  "success": true,
  "data": { ... },
  "error": null
}
```

On error:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "hint": "How to fix it",
    "retryable": true
  }
}
```

For `ask` and `history`, JSON output is produced by LLM converter agents (`avos_ask_agent_JSON_converter.md`, `avos_hisotry_agent_JSON_converter.md`) and requires the `REPLY_MODEL` environment variables.

For all other commands, JSON output is deterministic (no LLM dependency).

---

## AI agent integration

Avos ships with built-in integration files for AI coding platforms.

### Cursor

```
.cursor/
├── rules/avos-agent-workflow.mdc     # Always-on workflow rules
└── skills/
    ├── avos-session/SKILL.md         # Session lifecycle
    ├── avos-search/SKILL.md          # Memory search with avos ask
    ├── avos-history/SKILL.md         # Chronological history
    └── avos-ingest-pr/SKILL.md       # Single-PR ingest after push
```

### Claude Code

```
.claude/
├── CLAUDE.md                         # Project-level instructions
├── commands/
│   ├── avos-ask.md                   # /avos-ask slash command
│   ├── avos-history.md               # /avos-history
│   ├── avos-session-start.md         # /avos-session-start
│   ├── avos-session-end.md           # /avos-session-end
│   └── avos-ingest-pr.md             # /avos-ingest-pr
├── agents/
│   ├── avos-researcher.md            # Research context before code changes
│   └── avos-session-manager.md       # Manage session lifecycle
└── instincts/
    └── avos-workflow.yaml            # Auto-trigger behaviors
```

### OpenAI Codex / other platforms

```
.codex/instructions.md                # Community stub
.agents/README.md                     # Integration guide for new platforms
```

To add support for a new platform, follow the patterns in `.cursor/` and `.claude/`.

---

## Recommended workflow

### Before changing old code

```bash
avos ask "why does this function exist?"
avos history "module-or-function-name"
```

Understand constraints before editing.

### During a coding session

```bash
avos session-start "Fix retry backoff in payment worker"
# ... do work in Claude Code, Cursor, or terminal ...
avos session-end
```

Creates a durable implementation trail.

### After pushing a PR

```bash
avos ingest-pr org/repo 456
```

Ensures the PR context is available for future queries.

### When a new engineer or agent joins

```bash
avos ask "what is this subsystem responsible for?"
avos history "subsystem-name"
avos session-ask "how was this retry flow implemented?"
```

Gives newcomers the trajectory of the codebase, not just the current snapshot.

---

## Multi-agent parallel development

Avos supports multiple agents working in parallel via git worktrees:

```bash
# Create a worktree with automatic session start
avos worktree-add ../feature-x feature-branch "Implement auth" --agent agentA

# Or initialize an existing worktree
cd ../existing-worktree
avos worktree-init
avos session-start --agent agentB "Build pagination"
```

In a worktree, `--agent` is **required** to distinguish parallel sessions.

| Context   | `--agent`    | When omitted                  |
| --------- | ------------ | ----------------------------- |
| Main repo | Optional     | Falls back to `git user.name` |
| Worktree  | **Required** | Command blocks with error     |

---

## Architecture

```
avos_cli/
├── cli/main.py              # Typer CLI entry point, credential resolution
├── commands/                 # Orchestrators (one per command)
│   ├── connect.py            # Repository connection flow
│   ├── ingest.py             # 4-stage bulk ingest (PRs, issues, commits, docs)
│   ├── ingest_pr.py          # Single-PR ingest
│   ├── ask.py                # Search + synthesize + ground + render
│   ├── history.py            # Chronological search + synthesize + render
│   ├── session_start.py      # Session lifecycle: create state, spawn watcher
│   ├── session_end.py        # Stop watcher, build artifact, store, cleanup
│   ├── session_status.py     # Read-only session state check
│   └── session_ask.py        # Search session memory (Memory B)
├── artifacts/                # Builders that produce canonical text for memory
├── services/                 # Shared: Memory API, GitHub, LLM, citation validator
├── agents/                   # LLM prompt templates for output formatting
├── models/                   # Pydantic models (artifacts, config, query, API)
├── config/                   # State files, hash store, lock manager
└── utils/                    # Output formatting, logging, time helpers
```

**Design principles:**

- Each command is an independent orchestrator with constructor DI
- Stateless CLI, stateful memory (via `memory_id`)
- Graceful degradation: if LLM synthesis fails, fallback to evidence-backed raw output
- All 4 LLM agents stay in the pipeline for `ask`/`history` JSON output

---

## Output pipeline

Two categories of commands, two output strategies:

**LLM-powered commands** (`ask`, `history`, `session-ask`):

```
Raw artifacts from Memory API
  -> Formatter Agent (avos_ask_agent.md / avos_history_agent.md)
  -> ANSWER/EVIDENCE or TIMELINE/SUMMARY text
  -> if --json: JSON Converter Agent -> structured JSON
  -> if no --json: Rich terminal UI (panels, tables)
```

**Non-LLM commands** (`connect`, `ingest`, `session-*`, `ingest-pr`):

```
Typed Python objects (counters, IDs, state)
  -> if --json: deterministic dict -> json.dumps -> JSON envelope
  -> if no --json: Rich terminal UI
```

When synthesis fails, the fallback path still routes through the formatter agents to produce clean evidence-backed output.

---

## Development

### Setup

```bash
git clone https://github.com/Avos-Lab/avos-dev-cli.git
cd avos-dev-cli
pip install -e ".[dev]"
```

### Run tests

```bash
pytest                          # all unit tests
pytest tests/unit/              # unit only
pytest tests/contract/          # API contract tests
pytest -x --tb=long             # stop on first failure, verbose
```

### Lint and type check

```bash
ruff check avos_cli/
mypy avos_cli/
```

### Project structure

```
tests/
├── unit/                # Fast, isolated, no network
│   ├── commands/        # One test file per orchestrator
│   ├── services/        # Service-level tests
│   └── config/          # Config/state tests
├── contract/            # API boundary validation
└── integration/         # End-to-end workflows
```

Coverage target: 90%+ (enforced in CI).

---

## Environment variables

| Variable              | Required for                     | Description                                   |
| --------------------- | -------------------------------- | --------------------------------------------- |
| `AVOS_API_KEY`        | All commands                     | Avos Memory API key                           |
| `AVOS_API_URL`        | All commands                     | API endpoint (default: `https://api.avos.ai`) |
| `GITHUB_TOKEN`        | `connect`, `ingest`, `ingest-pr` | GitHub personal access token                  |
| `ANTHROPIC_API_KEY`   | `ask`, `history`, `session-ask`  | Anthropic API key for LLM synthesis           |
| `OPENAI_API_KEY`      | `ask`, `history`, `session-ask`  | Alternative: OpenAI API key                   |
| `REPLY_MODEL`         | `--json` for `ask`/`history`     | Model identifier for output formatting        |
| `REPLY_MODEL_URL`     | `--json` for `ask`/`history`     | API endpoint for reply model                  |
| `REPLY_MODEL_API_KEY` | `--json` for `ask`/`history`     | API key for reply model                       |

---

## Compliance and auditability

Session memory preserves a searchable trail of who changed what, why, what tests were run, and what risks remained. This is useful for engineering reviews, internal accountability, and regulated environments.

However: Avos is not itself a compliance certification. Session memory is **supporting evidence**, not a full compliance program. Your organization still needs its own access controls, retention policy, and control mappings.

---

## Documentation

- [User Guide](docs/user/README.md) — Command reference, troubleshooting
- [Contributor Guide](CONTRIBUTING.md) — Setup, testing, code style, PR process
- [Changelog](CHANGELOG.md) — Release history
- [Agent Integration Guide](.agents/README.md) — Adding new platform integrations

---

## Contributing

We welcome contributions to the CLI, integrations, and developer workflows. Please open an issue or discussion with your use case and the workflow you want Avos to support.

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and PR process.

---

## License

Apache-2.0
