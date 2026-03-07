# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
