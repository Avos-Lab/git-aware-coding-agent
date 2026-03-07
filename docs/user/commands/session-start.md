# avos session-start

Start a coding session with a goal and background activity capture.

## Usage

```bash
avos session-start <goal>
```

## Options

| Option | Description |
|--------|-------------|
| `goal` | Session goal description (required) |

## Examples

```bash
avos session-start "Fix payment retry bug"
avos session-start "Implement OAuth flow"
```

## Troubleshooting

- **AUTH_ERROR**: Set `AVOS_API_KEY`.
- **SESSION_ACTIVE_CONFLICT**: A session is already active. Run `avos session-end` first.
- **WATCHER_SPAWN_FAILED**: Check permissions and available processes.
