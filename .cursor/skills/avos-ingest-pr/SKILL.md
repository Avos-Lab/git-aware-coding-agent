---
description: Ingest a single PR into avos memory after pushing
globs: ["**/*"]
alwaysApply: false
---

# Avos Ingest PR

Use this skill when you need to ingest a single PR into repository memory after pushing.

## When to Use

- After pushing a PR to the remote repository
- After a PR is merged
- To ensure PR context is available for future queries

## Command

```bash
avos ingest-pr --json org/repo PR_NUMBER
```

## Examples

### Ingest a specific PR

```bash
avos ingest-pr --json myorg/myrepo 123
```

## Response Format

**Success (stored):**

```json
{
  "success": true,
  "data": {
    "pr_number": 123,
    "action": "stored",
    "note_id": "note-abc-123",
    "reason": null
  }
}
```

**Success (skipped - already ingested):**

```json
{
  "success": true,
  "data": {
    "pr_number": 123,
    "action": "skipped",
    "note_id": null,
    "reason": "already_ingested"
  }
}
```

**Error (PR not found):**

```json
{
  "success": false,
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Failed to fetch PR #999: PR not found",
    "retryable": true
  }
}
```

## Workflow

1. Push your PR to the remote repository
2. Get the PR number from GitHub
3. Run `avos ingest-pr --json org/repo PR_NUMBER`
4. Verify the response shows `"action": "stored"`

## When to Use vs Full Ingest

| Scenario | Command |
|----------|---------|
| Single PR after push | `avos ingest-pr org/repo 123` |
| Initial repository setup | `avos ingest org/repo --since 90d` |
| Periodic bulk update | `avos ingest org/repo --since 30d` |

## Error Handling

| Error Code | Meaning | Action |
|------------|---------|--------|
| `CONFIG_NOT_INITIALIZED` | Repo not connected | Run `avos connect` |
| `RESOURCE_NOT_FOUND` | PR doesn't exist | Check PR number |
| `UPSTREAM_UNAVAILABLE` | API down | Retry later |

## Required Environment Variables

- `AVOS_API_KEY` - Avos Memory API key
- `GITHUB_TOKEN` - GitHub personal access token

## Deduplication

The command automatically skips PRs that have already been ingested (based on content hash). This means:

- Safe to run multiple times
- Won't create duplicate entries
- Returns `"action": "skipped"` for duplicates
