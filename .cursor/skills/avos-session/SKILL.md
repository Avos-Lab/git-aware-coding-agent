---
description: Manage avos coding session lifecycle (start, status, end) for audit trails
globs: ["**/*"]
alwaysApply: false
---

# Avos Session Management

Use this skill when you need to manage coding session lifecycle for audit trails.

## When to Use

- Starting a new coding task
- Checking if a session is already active
- Ending a completed coding task
- Creating audit trails for AI agent activity

## Commands

### Check Session Status

Before starting a session, check if one is already active:

```bash
avos session-status --json
```

**Response when no session:**

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
  }
}
```

**Response when session is active:**

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
  }
}
```

### Start a Session

```bash
avos session-start --json "your goal description"
```

In a git worktree, always specify the agent:

```bash
avos session-start --json --agent agentA "your goal description"
```

**Success response:**

```json
{
  "success": true,
  "data": {
    "session_id": "sess_abc123",
    "goal": "your goal description",
    "branch": "main",
    "agent": "agentA",
    "started_at": "2026-03-11T10:00:00Z"
  }
}
```

**Error when session already active:**

```json
{
  "success": false,
  "error": {
    "code": "SESSION_ACTIVE_CONFLICT",
    "message": "A session is already active.",
    "hint": "Run 'avos session-end' first."
  }
}
```

### End a Session

```bash
avos session-end --json
```

**Success response:**

```json
{
  "success": true,
  "data": {
    "session_id": "sess_abc123",
    "goal": "your goal description",
    "author": "Developer <dev@example.com>",
    "files_modified": ["src/main.py", "tests/test_main.py"],
    "checkpoints": 5,
    "changes": "+150/-30",
    "warnings": []
  }
}
```

## Workflow

1. Check status: `avos session-status --json`
2. If inactive, start: `avos session-start --json "goal"`
3. Do your work
4. End session: `avos session-end --json`

## Error Handling

| Error Code | Meaning | Action |
|------------|---------|--------|
| `SESSION_ACTIVE_CONFLICT` | Session already running | End it first or continue |
| `SESSION_NOT_FOUND` | No active session | Start one first |
| `CONFIG_NOT_INITIALIZED` | Repo not connected | Run `avos connect` |
| `AGENT_REQUIRED` | In worktree without agent | Add `--agent` flag |
