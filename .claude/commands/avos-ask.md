---
description: Search repository memory for engineering context
allowed-tools: Bash
argument-hint: your question about the codebase
---

# Avos Ask

Search the repository memory for answers to your question.

## Usage

Run this command and parse the JSON output:

```bash
avos ask --json "$ARGUMENTS"
```

## Response Handling

Parse the JSON response:

```json
{
  "success": true,
  "data": {
    "format": "avos.ask.v1",
    "answer": { "text": "..." },
    "evidence": { "items": [...] }
  }
}
```

If `success` is false, check `error.code` and `error.hint` for guidance.

## Examples

- "why does authentication use JWT?"
- "how do other endpoints handle pagination?"
- "is there existing error handling middleware?"
