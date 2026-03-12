---
description: Ingest a single PR into repository memory
allowed-tools: Bash
argument-hint: org/repo PR_NUMBER
---

# Avos Ingest PR

Ingest a single PR into repository memory after pushing.

## Usage

```bash
avos ingest-pr --json $ARGUMENTS
```

## Response Handling

Parse the JSON response:

**Stored:**
```json
{
  "success": true,
  "data": {
    "pr_number": 123,
    "action": "stored",
    "note_id": "note-abc-123"
  }
}
```

**Skipped (already ingested):**
```json
{
  "success": true,
  "data": {
    "pr_number": 123,
    "action": "skipped",
    "reason": "already_ingested"
  }
}
```

## When to Use

- After pushing a PR to the remote repository
- After a PR is merged
- To ensure PR context is available for future queries

## Examples

- `myorg/myrepo 123`
- `company/project 456`
