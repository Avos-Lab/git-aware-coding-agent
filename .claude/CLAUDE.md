# Avos Dev CLI - Claude Code Integration

This repository uses **avos-dev-cli** for codebase memory and session tracking. Follow these instructions when working on this codebase.

## Project Overview

avos-dev-cli is a developer memory CLI that:
- Stores repository history (PRs, issues, commits, docs) in Avos Memory
- Enables semantic search over codebase context
- Tracks coding sessions for audit trails
- Provides chronological history of any subject

## Required Environment Variables

Ensure these are set before using avos commands:

```bash
export AVOS_API_KEY="your-avos-api-key"
export GITHUB_TOKEN="your-github-token"
export ANTHROPIC_API_KEY="your-anthropic-key"  # or OPENAI_API_KEY

# For JSON output formatting (optional but recommended)
export REPLY_MODEL="your-model-id"
export REPLY_MODEL_URL="https://api.example.com/v1/chat/completions"
export REPLY_MODEL_API_KEY="your-reply-model-key"
```

## Session Lifecycle

### Starting Work

Before making any code changes:

1. Check if a session is already active:
   ```bash
   avos session-status --json
   ```

2. If no session is active, start one:
   ```bash
   avos session-start --json "your goal description"
   ```

### During Work

The session automatically captures your activity. Use these commands to understand the codebase:

- **Search memory**: `avos ask --json "your question"`
- **Get history**: `avos history --json "subject"`

### Ending Work

When your task is complete:

```bash
avos session-end --json
```

### After Pushing PRs

After pushing a PR to the remote:

```bash
avos ingest-pr --json org/repo PR_NUMBER
```

## Best Practices

### Always Check History Before Modifying Code

Before changing existing code, especially unfamiliar code:

```bash
avos history --json "module or feature name"
avos ask --json "why was this implemented this way?"
```

This helps you understand:
- Why the code was written this way
- Who made previous changes and why
- Related PRs, issues, and commits

### Search Before Writing New Code

Before implementing new features:

```bash
avos ask --json "is there existing implementation for X?"
avos ask --json "how do other parts of the codebase handle Y?"
```

## Available Commands

| Command | Purpose |
|---------|---------|
| `avos session-status --json` | Check if session is active |
| `avos session-start --json "goal"` | Start a coding session |
| `avos session-end --json` | End the current session |
| `avos ask --json "question"` | Search memory for answers |
| `avos history --json "subject"` | Get chronological history |
| `avos ingest-pr --json org/repo N` | Ingest a single PR |

## JSON Output Format

All commands with `--json` return:

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

## Slash Commands

Use these slash commands for quick access:

- `/avos-ask` - Search repository memory
- `/avos-history` - Get chronological history
- `/avos-session-start` - Start a coding session
- `/avos-session-end` - End the current session
- `/avos-ingest-pr` - Ingest a PR after pushing

## Sub-Agents

- **avos-researcher** - Automatically searches memory and history before code changes
- **avos-session-manager** - Manages session lifecycle automatically
