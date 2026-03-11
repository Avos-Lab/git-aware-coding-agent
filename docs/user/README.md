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
pip install avos-cli
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

| Command                                    | Description                                   |
| ------------------------------------------ | --------------------------------------------- |
| [connect](commands/connect.md)             | Connect a repository to Avos Memory           |
| [ingest](commands/ingest.md)               | Ingest repository history                     |
| [ask](commands/ask.md)                     | Ask questions and get evidence-backed answers |
| [history](commands/history.md)             | Get chronological history of a subject        |
| [session-start](commands/session-start.md) | Start a coding session                        |
| [session-end](commands/session-end.md)     | End the current session                       |

## Global Options

- `--verbose` — Enable verbose debug output
- `--json` — Emit machine-readable JSON output (for AI agents/automation)

## JSON Output Mode (For AI Agents)

Use `--json` to get strict JSON output for `ask` and `history` commands:

```bash
avos --json ask "How does authentication work?"
avos --json history "payment retry logic"
```

JSON mode requires the reply model configuration:

| Variable              | Description                                                 |
| --------------------- | ----------------------------------------------------------- |
| `REPLY_MODEL`         | Model identifier (e.g. `Qwen/Qwen3-Coder-30B-A3B-Instruct`) |
| `REPLY_MODEL_URL`     | API endpoint (OpenAI-compatible chat completions)           |
| `REPLY_MODEL_API_KEY` | API key for the reply model                                 |

Output follows a strict envelope: `{"success": bool, "data": {...}, "error": {...}}`.

See [ask](commands/ask.md) and [history](commands/history.md) for schema details.

## Troubleshooting

See [troubleshooting](troubleshooting.md) for common issues and solutions.
