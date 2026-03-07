# avos session-end

End the current coding session and store a session memory artifact.

## Usage

```bash
avos session-end
```

## Options

None.

## Examples

```bash
avos session-end
```

## Troubleshooting

- **AUTH_ERROR**: Set `AVOS_API_KEY`.
- **SESSION_NOT_FOUND**: No active session. Run `avos session-start` first.
- **WATCHER_STOP_FAILED**: The background watcher may have exited. Session artifact is still created.
