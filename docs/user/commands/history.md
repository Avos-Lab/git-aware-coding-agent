# avos history

Get a chronological history of a subject or topic in the repository.

## Usage

```bash
avos history <subject>
avos --json history <subject>
```

## Options

| Option    | Description                                           |
| --------- | ----------------------------------------------------- |
| `subject` | Subject or topic for chronological history (required) |

## Global Options

| Option   | Description                                                      |
| -------- | ---------------------------------------------------------------- |
| `--json` | Emit machine-readable JSON output (for AI agents/automation)     |

## Examples

```bash
avos history "payment retry logic"
avos history "authentication flow"
avos history "PR #42"

# JSON mode for AI agents
avos --json history "payment retry logic"
```

## JSON Output Mode

When `--json` is passed, output is strict JSON conforming to the `avos.history.v1` schema:

```json
{
  "success": true,
  "data": {
    "format": "avos.history.v1",
    "raw_text": "...",
    "timeline": {
      "is_empty_history": false,
      "months": [
        {
          "month_label": "Mar 2026",
          "classification": "BUG FIX",
          "header_raw": "Mar 2026 — BUG FIX",
          "events": [
            { "line_raw": "...", "kind": "PR", "id": "#123", "title": "...", "author": "..." }
          ]
        }
      ],
      "unparsed_timeline_lines": []
    },
    "summary": { "text": "..." },
    "parse_warnings": []
  },
  "error": null
}
```

On failure, the envelope contains `"success": false` with an error object.

JSON mode requires the reply model configuration (see below).

## Reply Output (Optional)

Same as `avos ask`: set `REPLY_MODEL`, `REPLY_MODEL_URL`, and `REPLY_MODEL_API_KEY` to get decorated timeline/summary output and enable JSON mode.

## Troubleshooting

- **AUTH_ERROR**: Set `AVOS_API_KEY` and `ANTHROPIC_API_KEY`.
- **QUERY_EMPTY_RESULT**: No artifacts found. Run `avos ingest` first.
- **REPLY_SERVICE_UNAVAILABLE**: JSON mode requires `REPLY_MODEL`, `REPLY_MODEL_URL`, `REPLY_MODEL_API_KEY`.
