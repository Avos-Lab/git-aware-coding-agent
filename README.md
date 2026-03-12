# avos-dev-cli

**Git history for AI agents.**

<p align="center">
  <video src="docs/assets/avos-dev-cli.mp4" controls width="100%"></video>
</p>

**Demo video:** [docs/assets/avos-dev-cli.mp4](docs/assets/avos-dev-cli.mp4)

Avos gives AI coding agents persistent, queryable memory so they can remember **why code exists**, **what decisions shaped it**, and **how it was built** — before they modify it.

```
┌─────────────────────────────────────────────────────────────────┐
│                    Developer / AI Agent                         │
│              (Claude Code, Cursor, Terminal)                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Avos CLI                                 │
│    connect · ingest · ask · history · session-start · session-end│
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Avos Memory Layer                           │
├─────────────────────────────┬───────────────────────────────────┤
│   Repository Memory         │   Session Memory                  │
│   ├── PRs & commits         │   ├── session goals               │
│   ├── issues & comments     │   ├── files touched               │
│   ├── documentation         │   ├── decisions made              │
│   └── historical context    │   └── audit trail                 │
└─────────────────────────────┴───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│          Agents retrieve context before reasoning               │
│                    or modifying code                            │
└─────────────────────────────────────────────────────────────────┘
```

Works with **Claude Code**, **Cursor**, and the **terminal**. Python 3.10+. Apache-2.0.

---

## Quick Start (60 seconds)

```bash
# Install
pip install avos-dev-cli

# Set credentials
export AVOS_API_KEY="your-key"
export GITHUB_TOKEN="your-token"

# Connect your repository
avos connect org/repo

# Ingest history (last 90 days)
avos ingest org/repo --since 90d

# Ask a question
avos ask "Why do we use Kafka here?"
```

That's it. Your repository now has queryable memory.

---

## The Problem

AI coding agents forget.

They can read the current file tree, but they cannot know:

- why a function exists
- what constraints shaped a module
- which old assumptions still matter
- what happened in previous PRs
- how a feature was implemented across a session

This causes bad rewrites, repeated mistakes, and fragile changes.

## The Solution

Avos attaches **portable memory** to your repository.

Agents can query this memory before reasoning about code, giving them long-term context about the system — not just the current snapshot.

---

## What Avos Enables

- **Persistent memory** across agent sessions
- **PR-aware reasoning** about past changes
- **Queryable knowledge** from code, docs, and artifacts
- **Traceable decision history** for agents
- **Audit trails** for compliance and accountability
- **Portable memory** that moves between agents and tools

---

## Two Memory Planes

### Repository Memory (long-term)

Stores the durable history of the codebase: PRs, commits, issues, comments, and documentation.

Powers `avos ask` and `avos history`.

### Session Memory (implementation trail)

Stores the working context of each coding session: goal, files touched, decisions, errors, tests run, and remaining risks.

Powers `avos session-start`, `avos session-end`, and `avos session-ask`.

Together, these let you understand both the **history of the repository** and the **audit trail of how a change was built**.

---

## Example Use Cases

### AI coding agents

Agents can remember previous design decisions and reuse solutions across sessions.

```bash
avos ask "Why was retry scheduler added?"
avos history "retry scheduler"
```

### Engineering teams

Teams can query historical reasoning before modifying old code.

```bash
avos ask "What constraints shaped the auth module?"
```

### Autonomous workflows

Agents coordinating on complex tasks can share persistent knowledge.

```bash
avos session-start "Implement payment retry"
# ... agent works ...
avos session-end
```

### Onboarding

New engineers or agents can understand the trajectory of the codebase.

```bash
avos ask "What is this subsystem responsible for?"
avos session-ask "How was this retry flow implemented?"
```

---

## Command Reference

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
| `avos hook-install`                                     | Install pre-push hook (auto-installed on connect)               |

### Global Options

```
--json      Emit machine-readable JSON (for AI agents and automation)
--verbose   Enable debug output
--version   Show version
```

---

## Automatic Commit Sync

When you connect a repository, avos automatically installs a **pre-push git hook** that syncs commits to Avos Memory on every `git push`. This keeps your team's memory up-to-date without manual `avos ingest` runs.

---

## JSON Output for AI Agents

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

For `ask` and `history`, JSON output is produced by LLM converter agents and requires the `REPLY_MODEL` environment variables. For all other commands, JSON output is deterministic (no LLM dependency).

---

## AI Agent Integration

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
├── commands/                         # Slash commands
├── agents/                           # Sub-agents for research/session management
└── instincts/                        # Auto-trigger behaviors
```

### Other Platforms

```
.codex/instructions.md                # Community stub
.agents/README.md                     # Integration guide for new platforms
```

---

## Recommended Workflow

### Before changing old code

```bash
avos ask "why does this function exist?"
avos history "module-or-function-name"
```

### During a coding session

```bash
avos session-start "Fix retry backoff in payment worker"
# ... do work ...
avos session-end
```

### After pushing a PR

```bash
avos ingest-pr org/repo 456
```

---

## Multi-Agent Parallel Development

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

---

## Architecture

```
avos_cli/
├── cli/main.py              # Typer CLI entry point
├── commands/                # Orchestrators (one per command)
├── artifacts/               # Builders that produce canonical text for memory
├── services/                # Memory API, GitHub, LLM, citation validator
├── agents/                  # LLM prompt templates for output formatting
├── models/                  # Pydantic models
├── config/                  # State files, hash store, lock manager
└── utils/                   # Output formatting, logging
```

**Design principles:**

- Each command is an independent orchestrator with constructor DI
- Stateless CLI, stateful memory (via `memory_id`)
- Graceful degradation: if LLM synthesis fails, fallback to evidence-backed raw output

---

## Environment Variables

| Variable              | Required for                     | Description                                              |
| --------------------- | -------------------------------- | -------------------------------------------------------- |
| `AVOS_API_KEY`        | All commands                     | Avos Memory API key from `https://avoslab.com/`          |
| `AVOS_API_URL`        | All commands                     | API endpoint (default: `https://avosmemory.avoslab.com`) |
| `GITHUB_TOKEN`        | `connect`, `ingest`, `ingest-pr` | GitHub personal access token                             |
| `ANTHROPIC_API_KEY`   | `ask`, `history`, `session-ask`  | Anthropic API key for LLM synthesis                      |
| `OPENAI_API_KEY`      | `ask`, `history`, `session-ask`  | Alternative: OpenAI API key                              |
| `REPLY_MODEL`         | `--json` for `ask`/`history`     | Model identifier for output formatting                   |
| `REPLY_MODEL_URL`     | `--json` for `ask`/`history`     | API endpoint for reply model                             |
| `REPLY_MODEL_API_KEY` | `--json` for `ask`/`history`     | API key for reply model                                  |

---

## Development

```bash
git clone https://github.com/Avos-Lab/avos-dev-cli.git
cd avos-dev-cli
pip install -e ".[dev]"

# Run tests
pytest

# Lint and type check
ruff check avos_cli/
mypy avos_cli/
```

Coverage target: 90%+ (enforced in CI).

---

## Compliance and Auditability

Session memory preserves a searchable trail of who changed what, why, what tests were run, and what risks remained. This is useful for engineering reviews, internal accountability, and regulated environments.

However: Avos is not itself a compliance certification. Session memory is **supporting evidence**, not a full compliance program.

---

## Why This Project Exists

AI agents will become long-lived collaborators on codebases.

But without memory, they cannot accumulate knowledge. They forget decisions, repeat mistakes, and lose context between sessions.

Avos explores what persistent memory for autonomous agents should look like.

---

## Contributing

We welcome contributions to the CLI, integrations, and developer workflows.

Areas we're especially interested in:

- New memory connectors
- Retrieval algorithms
- Agent integrations (Codex, OpenCode, etc.)
- Developer tooling

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and PR process.

---

## Documentation

- [User Guide](docs/user/README.md) — Command reference, troubleshooting
- [Contributor Guide](CONTRIBUTING.md) — Setup, testing, code style
- [Changelog](CHANGELOG.md) — Release history
- [Agent Integration Guide](.agents/README.md) — Adding new platform integrations

---

## License

Apache-2.0
