# Public publication policy

This repository is an independently designed public tool. Its code,
documentation, fixtures, examples, issues, releases, and build artifacts must
remain separate from all non-public work.

## Allowed public material

- Original code and documentation created for this repository
- Obviously synthetic fixtures with invented identifiers
- Publicly documented, implementation-neutral concepts that may be reused
  under their applicable terms
- Contributions that can be reviewed and tested entirely from public context

## Material that must not be published

- Code, data, schemas, mappings, queries, configuration, or documentation from
  a private repository or workspace
- Patient, customer, employee, operational, or other non-public data, including
  transformed, sampled, or de-identified extracts
- Confidential identifiers, internal paths, credentials, tokens, or logs
- Private product, organization, repository, roadmap, architecture, or branding
  details
- Vendor or standards material that cannot be redistributed under its license

Public tests enforce generic secret, direct-identifier, and local-path checks.
Any screening for exact non-public names belongs in a private pre-publication
process outside this repository; the names themselves must not be encoded here.

When provenance or redistribution rights are uncertain, do not contribute the
material. Recreate the concept from public information with new synthetic data,
or leave it out.
