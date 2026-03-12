# avos hook-install

Install a git hook for automatic commit sync on push. When installed, every `git push` automatically syncs pushed commits to Avos Memory, enabling real-time team synchronization.

## Usage

```bash
avos hook-install [--force]
```

## Options

| Option | Description |
|--------|-------------|
| `--force`, `-f` | Overwrite existing pre-push hook |

## How It Works

1. Installs a `pre-push` hook in `.git/hooks/`
2. On every `git push`, the hook extracts commits being pushed
3. Commits are synced to Avos Memory using the same format as `avos ingest`
4. Team members can immediately query the new commits via `avos ask`

## Examples

```bash
# Install the hook (one-time setup)
avos hook-install

# Force reinstall if a hook already exists
avos hook-install --force
```

## Team Workflow

```bash
# Developer A pushes commits
git commit -m "feat: add login"
git push origin main
# [avos] Synced 1 commit(s) to memory

# Developer B can immediately query
avos ask "what was just pushed?"
# Shows Developer A's commit
```

## Uninstalling

To remove the hook:

```bash
avos hook-uninstall
```

Or manually delete `.git/hooks/pre-push`.

## Troubleshooting

- **CONFIG_NOT_INITIALIZED**: Run `avos connect org/repo` first.
- **Hook already exists**: Use `--force` to overwrite, or manually integrate `avos hook-sync` into your existing hook.
- **Commits not syncing**: Ensure `AVOS_API_KEY` is set in your environment.

## Technical Details

- The hook uses `pre-push` (runs before data transfer to remote)
- Commits are deduplicated using the same hash store as `avos ingest`
- The hook never blocks `git push` - errors are logged but push continues
- Works with git worktrees
