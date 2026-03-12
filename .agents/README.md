# Agent Integration Guide

This repository supports multiple AI coding agent platforms. Each platform has its own integration directory.

## Platform-Specific Integrations

| Platform | Directory | Status |
|----------|-----------|--------|
| Cursor IDE | `.cursor/` | Implemented |
| Claude Code | `.claude/` | Implemented |
| OpenAI Codex | `.codex/` | Community stub |

## Integration Structure

Each platform integration follows a similar pattern:

```
.platform/
├── README.md or PLATFORM.md    # Main instructions
├── commands/                    # Command wrappers
├── agents/                      # Sub-agents
├── skills/                      # Skills (Cursor)
├── rules/                       # Rules (Cursor)
└── instincts/                   # Instincts (Claude)
```

## Adding a New Platform

To add support for a new AI coding agent platform:

1. Create a directory: `.platform-name/`
2. Add main instructions file
3. Create command wrappers for avos commands
4. Add any platform-specific agents or skills
5. Submit a PR with your integration

## Available Avos Commands

All platforms should integrate these commands:

| Command | Purpose |
|---------|---------|
| `avos session-status --json` | Check if session is active |
| `avos session-start --json "goal"` | Start a coding session |
| `avos session-end --json` | End the current session |
| `avos ask --json "question"` | Search memory for answers |
| `avos history --json "subject"` | Get chronological history |
| `avos ingest-pr --json org/repo N` | Ingest a single PR |

## Workflow Guidelines

All platform integrations should follow these workflow guidelines:

1. **Session Lifecycle**: Start sessions before coding, end after completion
2. **Research Before Edit**: Check history and ask questions before modifying code
3. **Ingest After PR**: Ingest PRs after pushing to remote
4. **JSON Output**: Use `--json` for machine-readable output

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

## Contributing

Community contributions are welcome! Please:

1. Follow the existing patterns in `.cursor/` and `.claude/`
2. Include comprehensive documentation
3. Test with the target platform
4. Submit a PR with your integration
