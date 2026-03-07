# avos ask

Ask a natural-language question about the repository and get an evidence-backed answer.

## Usage

```bash
avos ask <question>
```

## Options

| Option | Description |
|--------|-------------|
| `question` | Natural language question about the repository (required) |

## Examples

```bash
avos ask "How does authentication work?"
avos ask "What was the rationale for the retry scheduler?"
avos ask "Who worked on the payment module?"
```

## Troubleshooting

- **AUTH_ERROR**: Set `AVOS_API_KEY` and `ANTHROPIC_API_KEY` (required for LLM synthesis).
- **QUERY_EMPTY_RESULT**: No relevant artifacts found. Run `avos ingest` first.
- **LLM_SYNTHESIS_ERROR**: Check `ANTHROPIC_API_KEY` and network connectivity.
