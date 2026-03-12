---
description: Get chronological history of a subject using avos history
globs: ["**/*"]
alwaysApply: false
---

# Avos History

Use this skill when you need chronological history of a subject in the repository.

## When to Use

Use this skill when at least one trigger applies:

- You are changing existing production behavior
- You are refactoring or touching shared/unfamiliar modules
- The change is medium/large (multi-file, broad behavior impact)
- You need to understand prior constraints before redesigning logic

You can skip for low-risk tasks:

- Docs/comments/typo-only edits
- New isolated files with no modification to existing behavior
- Test-only updates not affecting runtime behavior

## Command

```bash
avos history --json "subject or topic"
```

## Examples

### Module History

```bash
avos history --json "authentication module"
```

### Feature Evolution

```bash
avos history --json "user registration flow"
```

### File History

```bash
avos history --json "database connection handling"
```

## Response Format

**Success with timeline:**

```json
{
  "success": true,
  "data": {
    "format": "avos.history.v1",
    "raw_text": "...",
    "timeline": {
      "is_empty_history": false,
      "months": [
        {
          "month": "2026-01",
          "events": [
            {
              "type": "pr",
              "ref": "123",
              "title": "Add JWT authentication",
              "author": "developer"
            }
          ]
        }
      ],
      "unparsed_timeline_lines": []
    },
    "summary": {
      "text": "The authentication module was introduced in January 2026..."
    },
    "parse_warnings": []
  }
}
```

**No history found:**

```json
{
  "success": true,
  "data": {
    "format": "avos.history.v1",
    "timeline": {
      "is_empty_history": true,
      "months": []
    },
    "summary": {
      "text": "No engineering history found for \"subject\"."
    }
  }
}
```

## Best Practices

1. **Check history before modifying**: Always understand the context before changing existing code
2. **Use specific subjects**: "payment processing" is better than "payments"
3. **Review the timeline**: Understand the evolution before making changes

## Workflow

1. Identify the code you want to modify
2. If trigger conditions match, run `avos history --json "relevant subject"`
3. Review the timeline and summary
4. Understand why decisions were made
5. Make informed changes

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
