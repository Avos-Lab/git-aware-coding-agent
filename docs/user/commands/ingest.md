# avos ingest

Ingest repository history (PRs, issues, commits, docs) into Avos Memory.

## Usage

```bash
avos ingest <repo> [--since <window>]
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `repo` | — | Repository slug in `org/repo` format (required) |
| `--since` | `90d` | Time window, e.g. `90d` for 90 days |

## Examples

```bash
avos ingest myorg/my-repo
avos ingest myorg/my-repo --since 30d
avos ingest myorg/my-repo --since 180d
```

## Troubleshooting

- **AUTH_ERROR**: Set `AVOS_API_KEY` and `GITHUB_TOKEN`.
- **INGEST_LOCK_CONFLICT**: Another ingest is running. Wait for it to finish.
- **REPOSITORY_CONTEXT_ERROR**: Run from inside the repository.
