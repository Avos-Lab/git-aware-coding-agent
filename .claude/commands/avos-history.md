---
description: Get chronological history of a subject in the repository
allowed-tools: Bash
argument-hint: subject or topic for timeline
---

# Avos History

Get the chronological history of a subject in the repository.

## Usage

Run this command and parse the JSON output:

```bash
avos history --json "$ARGUMENTS"
```

## Response Handling

Parse the JSON response:

```json
{
  "success": true,
  "data": {
    "format": "avos.history.v1",
    "timeline": { "months": [...] },
    "summary": { "text": "..." }
  }
}
```

If `success` is false, check `error.code` and `error.hint` for guidance.

## Examples

- "authentication module"
- "user registration flow"
- "database connection handling"
