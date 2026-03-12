# avos ingest-pr

Ingest a single PR into Avos Memory.

## Usage

```bash
avos ingest-pr [--json] <org/repo> <pr_number>
```

## Description

Fetches a single PR by number, builds its artifact, and stores it in Avos Memory. Use this after pushing a PR to ensure its context is available for future queries.

The command automatically skips PRs that have already been ingested (based on content hash).

## Arguments

| Argument    | Description                              |
| ----------- | ---------------------------------------- |
| `org/repo`  | Repository slug in 'org/repo' format     |
| `pr_number` | PR number to ingest                      |

## Options

| Option   | Description                          |
| -------- | ------------------------------------ |
| `--json` | Emit machine-readable JSON output    |

## Output

### Human-Readable (default)

```
┌─ PR #123 Ingested ───────────────────────────────┐
│ Title: Add authentication module                 │
│ Author: developer                                │
│ Files: 5                                         │
│ Note ID: note-abc-12...                          │
└──────────────────────────────────────────────────┘
```

When skipped (already ingested):
```
PR #123 already ingested. Skipping.
```

### JSON Output

**Stored:**

```json
{
  "success": true,
  "data": {
    "pr_number": 123,
    "action": "stored",
    "note_id": "note-abc-123",
    "reason": null
  },
  "error": null
}
```

**Skipped (already ingested):**

```json
{
  "success": true,
  "data": {
    "pr_number": 123,
    "action": "skipped",
    "note_id": null,
    "reason": "already_ingested"
  },
  "error": null
}
```

## Exit Codes

| Code | Meaning                           |
| ---- | --------------------------------- |
| 0    | Success (stored or skipped)       |
| 1    | Precondition failure (bad args)   |
| 2    | Hard external failure (API error) |

## Examples

```bash
# Ingest PR #123 from myorg/myrepo
avos ingest-pr myorg/myrepo 123

# Ingest with JSON output
avos ingest-pr --json myorg/myrepo 123

# Use in a script after pushing
PR_NUM=$(gh pr view --json number -q .number)
avos ingest-pr --json myorg/myrepo "$PR_NUM"
```

## When to Use

| Scenario                  | Command                            |
| ------------------------- | ---------------------------------- |
| Single PR after push      | `avos ingest-pr org/repo 123`      |
| Initial repository setup  | `avos ingest org/repo --since 90d` |
| Periodic bulk update      | `avos ingest org/repo --since 30d` |

## Environment Variables

| Variable       | Description                    |
| -------------- | ------------------------------ |
| `AVOS_API_KEY` | Avos Memory API key (required) |
| `GITHUB_TOKEN` | GitHub personal access token   |

## See Also

- [ingest](ingest.md) - Ingest full repository history
- [connect](connect.md) - Connect a repository to Avos Memory
