# avos session-ask

Ask a natural-language question about current session and live context (Memory B).

Uses hybrid search over session memory: session artifacts from `avos session-end` and related live context data.

## Usage

```bash
avos session-ask <question>
```

## Options

| Option | Description |
|--------|-------------|
| `question` | Natural language question about session/live context (required) |

## Examples

```bash
avos session-ask "What is currently being worked on?"
avos session-ask "Who touched the auth module recently?"
```

## Reply Output (Optional)

Same as `avos ask`: set `REPLY_MODEL`, `REPLY_MODEL_URL`, and `REPLY_MODEL_API_KEY` for decorated terminal output.

## Troubleshooting

- **AUTH_ERROR**: Set `AVOS_API_KEY` and `ANTHROPIC_API_KEY`.
- **No matching evidence**: Run `avos session-start` or `avos session-end` first to populate session memory.
