# Security policy

## Supported version

Security fixes are applied to the latest release.

## Reporting a vulnerability

Use the repository's private vulnerability-reporting option under **Security → Advisories** when available. Do not publish exploit details in a public issue.

If private reporting is unavailable, open a public issue that asks the maintainer to establish a private contact channel. Include no vulnerability details, logs, data, or reproduction steps in that issue.

This project must never receive real patient or employer data. If you discover that sensitive information has been contributed, do not copy, quote, or attach it elsewhere. Report only the affected repository path and commit through the private channel.

## Scope

The case validator, result comparator, suite verifier, and composite Action
process local synthetic or aggregate contract files. Their verification paths
impose file, row, cell, key, and rendered-report bounds and reject symlinked
verification trees. These controls limit accidental resource abuse; they do not
make the tools appropriate for production health information or arbitrary
untrusted uploads.

The optional reference runners are developer utilities for the bundled synthetic
cases. They do not sandbox caller-supplied SQL and should not be exposed as an
untrusted query service.

The Action executes only this repository's dependency-free verifier. It accepts
no customer command, script, SQL, token, or network location. Callers should use
the minimal `contents: read` permission and pin a reviewed full commit SHA when
an immutable dependency is required.
