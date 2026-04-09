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

**Solution:** Create a GitHub Personal Access Token and set it:

```bash
export GITHUB_TOKEN="ghp_..."   # or github_pat_... for fine-grained
```

**Classic tokens:** Use the `repo` scope.

**Fine-grained tokens (github*pat*...):**

1. Go to [GitHub → Settings → Developer settings → Personal access tokens](https://github.com/settings/tokens?type=beta)
2. Create a fine-grained token
3. Under **Repository access**, select **Only select repositories** and add your repo (e.g. `smahmudrahat/any_repo`)
4. Under **Repository permissions**, set:
   - **Metadata:** Read-only
   - **Pull requests:** Read-only
   - **Issues:** Read-only
5. Generate and copy the token

Without these permissions, private repos return 404 (GitHub hides existence if you lack access).

### AUTH_ERROR: ANTHROPIC_API_KEY required

**Cause:** Required for `ask` and `history` (LLM synthesis).

**Solution:** Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Repository Errors

### RESOURCE_NOT_FOUND: Repository owner/repo not found on GitHub

**Cause:** The token cannot access the repository. For **private repos**, this usually means:

- Fine-grained token: repo not in "Repository access" list, or missing Metadata/Pull requests/Issues permissions
- Classic token: missing `repo` scope
- Token expired or revoked

**Solution:** Ensure your token has access to the repo. For fine-grained tokens, see the GITHUB_TOKEN section above.

### REPOSITORY_CONTEXT_ERROR

**Cause:** Command was run outside a git repository.

**Solution:** Run from a directory that contains a `.git` folder, or from a subdirectory of such a repo.

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
