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

| Command | Description |
|---------|-------------|
| [connect](commands/connect.md) | Connect a repository to Avos Memory |
| [ingest](commands/ingest.md) | Ingest repository history |
| [ask](commands/ask.md) | Ask questions and get evidence-backed answers |
| [history](commands/history.md) | Get chronological history of a subject |
| [session-start](commands/session-start.md) | Start a coding session |
| [session-end](commands/session-end.md) | End the current session |
| [watch](commands/watch.md) | Watch for file changes and publish WIP |
| [team](commands/team.md) | Show active team members and their work |
| [conflicts](commands/conflicts.md) | Detect merge conflicts with team work |

## Global Options

- `--verbose` — Enable verbose debug output
- `--json` — Emit machine-readable JSON output

## Troubleshooting

See [troubleshooting](troubleshooting.md) for common issues and solutions.
