# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in avos-cli, please report it responsibly.

**Do not** open a public GitHub issue for security vulnerabilities.

Instead:

1. Email the maintainers at [security@avos.ai](mailto:security@avos.ai) with a description of the vulnerability.
2. Include steps to reproduce, impact assessment, and any suggested fixes if you have them.
3. Allow a reasonable time (at least 90 days) for a fix before any public disclosure.

We will acknowledge receipt and provide updates on our progress. We appreciate your efforts to disclose your findings responsibly.

## Security Practices

- **Secrets**: API keys and tokens are read from environment variables or `.avos/config.json`. Never commit secrets to the repository.
- **Output**: The CLI redacts API keys and tokens from logs. Use `--json` for machine-readable output without progress noise.
- **CI**: Secret scanning (gitleaks) runs in CI before any publish step.
- **Dependencies**: We use pinned or minimum-version constraints. Run `pip audit` to check for known vulnerabilities.
