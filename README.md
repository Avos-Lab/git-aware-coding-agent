# avos

Developer memory CLI for repositories. Connect your repo to Avos Memory, ingest PRs/issues/commits, and ask natural-language questions with evidence-backed answers.

## Quick Start

### 1. Get your API key

Sign up at [Avos](https://avos.ai) to obtain an API key. Set it in your environment:

```bash
export AVOS_API_KEY="your-api-key"
```

For `connect` and `ingest`, you also need a GitHub token. For `ask` and `history`, you need an Anthropic API key. See [User Guide](docs/user/README.md) for details.

### 2. Install

```bash
pip install avos-cli
```

### 3. Connect and ingest

From inside a git repository:

```bash
avos connect org/repo
avos ingest org/repo --since 90d
```

### 4. Ask

```bash
avos ask "How does authentication work?"
```

## Documentation

- [User Guide](docs/user/README.md) — Quick-start, command reference, troubleshooting
- [Contributor Guide](CONTRIBUTING.md) — Setup, testing, code style, PR process

## Commands

| Command | Description |
|---------|-------------|
| `connect` | Connect a repository to Avos Memory |
| `ingest` | Ingest PRs, issues, commits, docs |
| `ask` | Ask questions, get evidence-backed answers |
| `history` | Chronological history of a subject |
| `session-start` / `session-end` | Coding session with background capture |
| `watch` | Publish WIP activity to team memory |
| `team` | Show active team members and their work |
| `conflicts` | Detect merge conflicts with team work |

## License

Apache-2.0
