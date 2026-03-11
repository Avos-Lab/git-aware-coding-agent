# avos ask

Ask a natural-language question about the repository and get an evidence-backed answer.

## Usage

```bash
avos ask <question>
avos --json ask <question>
```

## Options

| Option     | Description                                               |
| ---------- | --------------------------------------------------------- |
| `question` | Natural language question about the repository (required) |

## Global Options

| Option   | Description                                                      |
| -------- | ---------------------------------------------------------------- |
| `--json` | Emit machine-readable JSON output (for AI agents/automation)     |

## Examples

```bash
avos ask "How does authentication work?"
avos ask "What was the rationale for the retry scheduler?"
avos ask "Who worked on the payment module?"

# JSON mode for AI agents
avos --json ask "How does authentication work?"
```

## JSON Output Mode

When `--json` is passed, output is strict JSON conforming to the `avos.ask.v1` schema:

```json
{
  "success": true,
  "data": {
    "format": "avos.ask.v1",
    "raw_text": "...",
    "answer": { "text": "..." },
    "evidence": {
      "is_none": false,
      "items": [
        { "line_raw": "...", "kind": "PR", "id": "#123", "title": "...", "author": "...", "date_label": "Mar 2026" }
      ],
      "unparsed_lines": []
    },
    "parse_warnings": []
  },
  "error": null
}
```

On failure, the envelope contains `"success": false` with an error object:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "CONFIG_NOT_INITIALIZED",
    "message": "...",
    "hint": "Run 'avos connect org/repo' first.",
    "retryable": false
  }
}
```

JSON mode requires the reply model configuration (see below).

## Reply Output (Optional)

To get clean, decorated terminal output (and enable JSON mode), set these environment variables (e.g. in `.env`):

| Variable              | Description                                                 |
| --------------------- | ----------------------------------------------------------- |
| `REPLY_MODEL`         | Model identifier (e.g. `Qwen/Qwen3-Coder-30B-A3B-Instruct`) |
| `REPLY_MODEL_URL`     | API endpoint (OpenAI-compatible chat completions)           |
| `REPLY_MODEL_API_KEY` | API key for the reply model                                 |

When configured, the reply layer formats both successful and fallback output for readability. If the reply model fails, a regex-based fallback formatter is used.

## Troubleshooting

- **AUTH_ERROR**: Set `AVOS_API_KEY` and `ANTHROPIC_API_KEY` (required for LLM synthesis).
- **QUERY_EMPTY_RESULT**: No relevant artifacts found. Run `avos ingest` first.
- **LLM_SYNTHESIS_ERROR**: Check `ANTHROPIC_API_KEY` and network connectivity.
- **REPLY_SERVICE_UNAVAILABLE**: JSON mode requires `REPLY_MODEL`, `REPLY_MODEL_URL`, `REPLY_MODEL_API_KEY`.
