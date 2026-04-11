# Codex Integration (Community)

This directory is reserved for OpenAI Codex CLI integration.

## Reference Implementations

See these directories for reference implementations:

- `.cursor/` - Cursor IDE integration (skills + rules)
- `.claude/` - Claude Code integration (commands + agents + instincts)

## Contributing

Community contributions for Codex integration are welcome. Follow the patterns established in `.cursor/` and `.claude/`:

1. **Instructions file**: Main configuration and workflow guidance
2. **Commands**: Individual command wrappers
3. **Agents**: Specialized sub-agents for specific tasks

## Avos Commands

The following avos commands are available for integration:

| Command | Purpose |
|---------|---------|
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

## Required Environment Variables

- `AVOS_API_KEY` - Avos Memory API key
- `GITHUB_TOKEN` - GitHub personal access token
- `OPENAI_API_KEY` (default) or `ANTHROPIC_API_KEY` (when using Anthropic) - For LLM synthesis

For JSON output formatting:
- `REPLY_MODEL` - Model identifier
- `REPLY_MODEL_URL` - API endpoint
- `REPLY_MODEL_API_KEY` - API key
