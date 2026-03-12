---
description: End the current coding session and store audit trail
allowed-tools: Bash
argument-hint: (no arguments needed)
---

# Avos Session End

End the current coding session and store the audit trail in memory.

## Usage

```bash
avos session-end --json
```

## Response Handling

Parse the JSON response:

```json
{
  "success": true,
  "data": {
    "session_id": "sess_abc123",
    "goal": "your goal",
    "author": "Developer <dev@example.com>",
    "files_modified": ["src/main.py"],
    "checkpoints": 5,
    "changes": "+150/-30",
    "warnings": []
  }
}
```

If `success` is false and `error.code` is `SESSION_NOT_FOUND`, no session is active.

## When to Use

- After completing a coding task
- Before switching to a different task
- At the end of a work session
