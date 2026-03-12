# avos connect

Connect a repository to Avos Memory. Creates two memory spaces:

- **Memory A (past)**: PR history, commits, issues, docs. Used by `avos ask`, `avos history`, and `avos ingest`.
- **Memory B (session)**: Session artifacts. Used by `avos session-start`, `avos session-end`, and `avos session-ask`.

## Usage

```bash
avos connect <repo>
```

## Options

| Option | Description                                     |
| ------ | ----------------------------------------------- |
| `repo` | Repository slug in `org/repo` format (required) |

## Examples

```bash
avos connect myorg/my-repo
avos connect owner/project-name
```

## Troubleshooting

- **AUTH_ERROR**: Set `AVOS_API_KEY` and `GITHUB_TOKEN` in your environment.
- **REPOSITORY_CONTEXT_ERROR**: Run from inside a git repository (a directory containing `.git`).
