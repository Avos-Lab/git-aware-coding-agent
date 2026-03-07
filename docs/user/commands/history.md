# avos history

Get a chronological history of a subject or topic in the repository.

## Usage

```bash
avos history <subject>
```

## Options

| Option | Description |
|--------|-------------|
| `subject` | Subject or topic for chronological history (required) |

## Examples

```bash
avos history "payment retry logic"
avos history "authentication flow"
avos history "PR #42"
```

## Troubleshooting

- **AUTH_ERROR**: Set `AVOS_API_KEY` and `ANTHROPIC_API_KEY`.
- **QUERY_EMPTY_RESULT**: No artifacts found. Run `avos ingest` first.
