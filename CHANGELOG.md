# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Agent-Centric CLI Integration**: Full support for AI coding agents
  - `avos session-status` command: Check if a session is active before starting
  - `avos ingest-pr` command: Ingest a single PR after pushing
  - `--json` output for all commands (connect, ingest, session-start, session-end, session-ask)
  
- **Cursor IDE Integration** (`.cursor/`)
  - `avos-agent-workflow.mdc` rule for session lifecycle and search-before-edit
  - Skills: `avos-session`, `avos-search`, `avos-history`, `avos-ingest-pr`

- **Claude Code Integration** (`.claude/`)
  - `CLAUDE.md` project instructions
  - Slash commands: `/avos-ask`, `/avos-history`, `/avos-session-start`, `/avos-session-end`, `/avos-ingest-pr`
  - Sub-agents: `avos-researcher`, `avos-session-manager`
  - Instincts: `avos-workflow.yaml` with auto-trigger behaviors

- **Open-Source Extensibility**
  - `.codex/` stub for OpenAI Codex integration (community)
  - `.agents/README.md` integration guide for new platforms

### Changed

- JSON output envelope now includes `hint` and `retryable` fields in error responses
- All orchestrators now accept `json_output` parameter for consistent JSON output

## [1.0.0] - 2026-03-07

### Added

- **CI Pipeline** (AVOS-026): Staged GitHub Actions workflow (lint → unit → integration → contract → benchmark → coverage → secret-scan)
- **Contract tests**: API boundary validation for add_memory, search, delete_note at HTTP transport level
- **Output contract**: `print_json()`, `print_verbose()`, `create_progress(suppress=)` for JSON/verbose modes
- **Global CLI flags**: `--verbose` and `--json` on root callback
- **Documentation**: User guide, command reference (9 commands), troubleshooting, contributor guide
- **Packaging**: `[full]` optional dependency group (anthropic), project URLs, install smoke test
- **Release governance**: SECURITY.md, CHANGELOG.md, TestPyPI publish workflow

### Changed

- Version bumped from 0.5.0 to 1.0.0
- Development status: Production/Stable
