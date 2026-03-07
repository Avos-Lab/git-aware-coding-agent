# avos watch

Watch for file changes and publish WIP activity to team memory.

## Usage

```bash
avos watch [--stop]
```

## Options

| Option | Description |
|--------|-------------|
| `--stop` | Stop the active watch process |

## Examples

```bash
avos watch
avos watch --stop
```

## Troubleshooting

- **AUTH_ERROR**: Set `AVOS_API_KEY`.
- **WATCH_ACTIVE_CONFLICT**: A watch is already running. Use `avos watch --stop` first.
- **WATCH_NOT_FOUND**: No active watch to stop.
