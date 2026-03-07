# avos conflicts

Detect potential merge conflicts with active team work.

## Usage

```bash
avos conflicts [--strict]
```

## Options

| Option | Description |
|--------|-------------|
| `--strict` | Promote symbol overlaps to HIGH severity |

## Examples

```bash
avos conflicts
avos conflicts --strict
```

## Troubleshooting

- **AUTH_ERROR**: Set `AVOS_API_KEY`.
- **REPOSITORY_CONTEXT_ERROR**: Run from inside a connected repository.
- **SUBSYSTEM_MAP_INVALID**: Check `.avos` config and subsystem mapping.
