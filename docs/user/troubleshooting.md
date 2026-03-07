# Troubleshooting

Common issues and solutions for the avos CLI.

## Authentication Errors

### AUTH_ERROR: AVOS_API_KEY required

**Cause:** The Avos Memory API key is not set.

**Solution:** Get your API key from [Avos](https://avos.ai) and set it:

```bash
export AVOS_API_KEY="your-api-key"
```

Or add it to a `.env` file in your project root.

### AUTH_ERROR: GITHUB_TOKEN required

**Cause:** Required for `connect` and `ingest` to access GitHub.

**Solution:** Create a GitHub Personal Access Token with `repo` scope and set:

```bash
export GITHUB_TOKEN="ghp_..."
```

### AUTH_ERROR: ANTHROPIC_API_KEY required

**Cause:** Required for `ask` and `history` (LLM synthesis).

**Solution:** Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Repository Errors

### REPOSITORY_CONTEXT_ERROR

**Cause:** Command was run outside a git repository.

**Solution:** Run from a directory that contains a `.git` folder, or from a subdirectory of such a repo.

## Session and Watch Errors

### SESSION_ACTIVE_CONFLICT

**Cause:** Trying to start a session when one is already active.

**Solution:** Run `avos session-end` first, then `avos session-start`.

### WATCH_ACTIVE_CONFLICT

**Cause:** Trying to start watch when it is already running.

**Solution:** Run `avos watch --stop` first.

## API and Network

### UPSTREAM_UNAVAILABLE

**Cause:** Avos Memory API or GitHub API unreachable (timeout, 5xx, etc.).

**Solution:** Check network connectivity. The CLI retries transient failures. If it persists, check [Avos status](https://avos.ai) or GitHub status.

### RATE_LIMIT_ERROR (429)

**Cause:** Too many requests to an API.

**Solution:** Wait and retry. The CLI respects `retry_after` when provided.

## Config and State

### CONFIG_NOT_INITIALIZED

**Cause:** `.avos/config.json` is missing or invalid.

**Solution:** Run `avos connect org/repo` to initialize.

### INGEST_LOCK_CONFLICT

**Cause:** Another ingest is running for the same repo.

**Solution:** Wait for the other ingest to finish, or remove the lock file in `.avos/` if you are sure no ingest is running.
