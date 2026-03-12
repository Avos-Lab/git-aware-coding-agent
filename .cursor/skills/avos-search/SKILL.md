---
description: Search repository memory with avos ask for engineering context
globs: ["**/*"]
alwaysApply: false
---

# Avos Search (Ask)

Use this skill when you need to search repository memory for engineering context.

## When to Use

Use this skill when at least one trigger applies:

- You are editing existing production code in an unfamiliar/shared module
- You expect a medium/large change (multi-file, refactor, behavior change)
- You need design rationale before changing architecture/API/auth/data flow
- You need to avoid duplicating an existing pattern

You can skip this skill for low-risk tasks:

- Docs/comments/typo-only changes
- New isolated file creation without touching existing behavior
- Test-only updates that do not alter production logic

## Command

```bash
avos ask --json "your question about the codebase"
```

## Examples

### Understanding Code Decisions

```bash
avos ask --json "why does the authentication module use JWT instead of sessions?"
```

### Finding Existing Patterns

```bash
avos ask --json "how do other API endpoints handle pagination?"
```

### Checking for Existing Functionality

```bash
avos ask --json "is there existing error handling middleware?"
```

## Response Format

**Success with answer:**

```json
{
  "success": true,
  "data": {
    "format": "avos.ask.v1",
    "raw_text": "...",
    "answer": {
      "text": "The authentication module uses JWT because..."
    },
    "evidence": {
      "is_none": false,
      "items": [
        {
          "type": "pr",
          "ref": "123",
          "title": "Implement JWT auth",
          "author": "developer"
        }
      ],
      "unparsed_lines": []
    },
    "parse_warnings": []
  }
}
```

**No matching evidence:**

```json
{
  "success": true,
  "data": {
    "format": "avos.ask.v1",
    "answer": {
      "text": "No matching evidence found in repository memory."
    },
    "evidence": {
      "is_none": true,
      "items": []
    }
  }
}
```

## Best Practices

1. **Be specific**: "how does user authentication work?" is better than "auth?"
2. **Include context**: "why does the login API return 401 instead of 403?" is better than "login error"
3. **Use for high-risk edits**: Trigger this before substantial or unfamiliar code edits
4. **Skip for trivial edits**: Avoid unnecessary memory calls for low-risk cosmetic changes

## Error Handling

| Error Code | Meaning | Action |
|------------|---------|--------|
| `CONFIG_NOT_INITIALIZED` | Repo not connected | Run `avos connect` |
| `REPLY_SERVICE_UNAVAILABLE` | JSON requires reply model | Set REPLY_MODEL env vars |
| `UPSTREAM_UNAVAILABLE` | Memory API down | Retry later |

## Required Environment Variables

For JSON output:
- `REPLY_MODEL` - Model identifier
- `REPLY_MODEL_URL` - API endpoint
- `REPLY_MODEL_API_KEY` - API key
