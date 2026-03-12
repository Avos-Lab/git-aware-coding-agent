---
description: Start a coding session for audit trail
allowed-tools: Bash
argument-hint: goal description for the session
---

# Avos Session Start

Start a coding session to create an audit trail of your work.

## Usage

First check if a session is already active:

```bash
avos session-status --json
```

If no session is active, start one:

```bash
avos session-start --json "$ARGUMENTS"
```

## Response Handling

Parse the JSON response:

```json
{
  "success": true,
  "data": {
    "session_id": "sess_abc123",
    "goal": "your goal",
    "branch": "main",
    "started_at": "2026-03-11T10:00:00Z"
  }
}
```

If `success` is false and `error.code` is `SESSION_ACTIVE_CONFLICT`, a session is already running.

## Examples

- "Fix authentication bug in login flow"
- "Add pagination to user list API"
- "Refactor database connection handling"
