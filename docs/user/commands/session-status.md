# avos session-status

Check if a coding session is currently active.

## Usage

```bash
avos session-status [--json]
```

## Description

Reports whether a session is currently active, including session details and watcher status. Use this before `session-start` to avoid conflicts.

## Options

| Option   | Description                          |
| -------- | ------------------------------------ |
| `--json` | Emit machine-readable JSON output    |

## Output

### Human-Readable (default)

When no session is active:
```
No active session.
```

When a session is active:
```
┌─ Active Session ─────────────────────────────────┐
│ Session ID: sess_abc123                          │
│ Goal: Implement feature X                        │
│ Branch: feature/x                                │
│ Started: 2026-03-11T10:00:00Z                    │
│ Watcher: alive                                   │
└──────────────────────────────────────────────────┘
```

### JSON Output

```json
{
  "success": true,
  "data": {
    "active": true,
    "session_id": "sess_abc123",
    "goal": "Implement feature X",
    "branch": "feature/x",
    "started_at": "2026-03-11T10:00:00Z",
    "agent": "agentA",
    "watcher_alive": true
  },
  "error": null
}
```

When no session is active:

```json
{
  "success": true,
  "data": {
    "active": false,
    "session_id": null,
    "goal": null,
    "branch": null,
    "started_at": null,
    "agent": null,
    "watcher_alive": false
  },
  "error": null
}
```

## Exit Codes

| Code | Meaning                        |
| ---- | ------------------------------ |
| 0    | Success (status reported)      |
| 1    | Precondition failure (no config) |

## Examples

```bash
# Check session status
avos session-status

# Check status with JSON output
avos session-status --json

# Use in a script
if avos session-status --json | jq -e '.data.active' > /dev/null; then
  echo "Session is active"
else
  echo "No active session"
fi
```

## See Also

- [session-start](session-start.md) - Start a coding session
- [session-end](session-end.md) - End the current session
