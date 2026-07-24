# Security policy

## Supported version

Security fixes are applied to the latest release.

## Reporting a vulnerability

Use the repository's private vulnerability-reporting option under **Security → Advisories** when available. Do not publish exploit details in a public issue.

If private reporting is unavailable, open a public issue that asks the maintainer to establish a private contact channel. Include no vulnerability details, logs, data, or reproduction steps in that issue.

This project must never receive real patient or employer data. If you discover that sensitive information has been contributed, do not copy, quote, or attach it elsewhere. Report only the affected repository path and commit through the private channel.

## Scope

The reference runner processes local synthetic CSV files and opens no network connection. It is not designed to process untrusted uploads or production health information.
