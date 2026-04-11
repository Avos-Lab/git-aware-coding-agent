# avos User Guide

Developer memory CLI for repositories. Use avos to connect your repo to Avos Memory, ingest history, and ask natural-language questions.

## Quick Start

### 1. Get your API key

Sign up at [Avos](https://avos.ai) to obtain an API key. Set it in your environment:

```bash
export AVOS_API_KEY="your-api-key"
```

### 2. Install

```bash
pip install git-aware-coding-agent
```

### 3. Connect

From inside a git repository:

```bash
avos connect org/repo
```

This creates `.avos/config.json` and links the repo to Avos Memory.

### 4. Ingest

Load PRs, issues, commits, and docs into memory:

```bash
avos ingest org/repo --since 90d
```

### 5. Ask

Ask questions about the repository:

```bash
avos ask "How does authentication work?"
```

## Command Reference

| Command                            | Description                                   |
| ---------------------------------- | --------------------------------------------- |
| [connect](commands/connect.md)     | Connect a repository to Avos Memory           |
| [ingest](commands/ingest.md)       | Ingest repository history                     |
| [ingest-pr](commands/ingest-pr.md) | Ingest a single PR                            |
| [ask](commands/ask.md)             | Ask questions and get evidence-backed answers |
| [history](commands/history.md)     | Get chronological history of a subject        |

## Global Options

- `--verbose` — Enable verbose debug output
- `--json` — Emit machine-readable JSON output (for AI agents/automation)

## JSON Output Mode (For AI Agents)

All commands support `--json` for machine-readable output:

```bash
avos --json ask "How does authentication work?"
avos --json history "payment retry logic"
avos --json ingest-pr org/repo 123
```

For `ask` and `history` commands, JSON mode requires the reply model configuration:

| Variable              | Description                                                 |
| --------------------- | ----------------------------------------------------------- |
| `REPLY_MODEL`         | Model identifier (e.g. `Qwen/Qwen3-Coder-30B-A3B-Instruct`) |
| `REPLY_MODEL_URL`     | API endpoint (OpenAI-compatible chat completions)           |
| `REPLY_MODEL_API_KEY` | API key for the reply model                                 |

Output follows a strict envelope:

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

See [ask](commands/ask.md) and [history](commands/history.md) for schema details.

## AI Agent Integration

avos-dev-cli is designed to work seamlessly with AI coding agents. Integration files are provided for:

- **Cursor IDE**: `.cursor/rules/` and `.cursor/skills/`
- **Claude Code**: `.claude/` with commands, agents, and instincts
- **OpenAI Codex**: `.codex/` (community stub)

See `.agents/README.md` for the integration guide.

### Agent Workflow

1. **Research**: `avos history --json "subject"` and `avos ask --json "question"`
2. **Code**: Make your changes
3. **After PR**: `avos ingest-pr --json org/repo PR_NUMBER`

## Troubleshooting

See [troubleshooting](troubleshooting.md) for common issues and solutions.
