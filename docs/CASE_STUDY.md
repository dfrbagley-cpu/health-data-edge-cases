# Product case study

**Intended users.** Healthcare analytics and data-platform teams turning changing source data into trustworthy operational measures.

**Problem.** A pipeline can run successfully and still return plausible but incorrect results when source versions, mappings, statuses, relationship keys, or event grain are inconsistent.

**Product decision.** I chose small, implementation-neutral synthetic contracts rather than a vendor-specific healthcare model. Each case isolates one consequential failure mode, states the governing rule, and provides a verifiable answer.

**My role.** I selected the problems; defined the healthcare-domain rules; designed the schemas and contracts; set scope, priorities, and acceptance criteria; directed the user experience; and validated the results. AI-assisted development and a [credited open-source contribution](https://github.com/dfrbagley-cpu/health-data-edge-cases/pull/8) accelerated implementation; responsibility for product decisions and validation remained mine.

**Repository evidence.** Five failure modes contain 72 executable expectations. Portable SQL runs in SQLite and DuckDB through a Python validation and orchestration harness, the calculations are cross-checked by an independent base-R implementation, and a versioned, digest-bound contract catalogue supports downstream consumers.

**Limits of the evidence.** These checks demonstrate reproducibility and explicit acceptance criteria. They do not establish external adoption, production deployments, or measured customer impact.

**Boundaries.** This is an implementation-neutral public conformance tool: not certification, an official reporting standard, or a hospital production implementation. It contains no patient information, employer data, licensed standards, or proprietary vendor schemas. The repository's [publication policy](../PUBLICATION_POLICY.md) keeps all public work separate from non-public code, data, schemas, identifiers, branding, and roadmaps.

Across the public portfolio, the trusted-data path is: **synthetic source fixtures → structural validation → governed transformations → expected metrics and quality signals → versioned contract catalogue → pinned [Toolkit](https://dfrbagley-cpu.github.io/healthcare-reporting-toolkit/) consumer → exportable analysis receipts**.

## Inspect the work

| Product or technical decision | Reviewable evidence |
|---|---|
| Make a silent reporting error reproducible | [Unmapped-program fixture and governing rule](../cases/unmapped-program-retention) |
| Define acceptance before implementation | [Committed expected results](../cases/unmapped-program-retention/expected_metrics.csv) |
| Preserve useful activity while surfacing quality problems | [Portable reference SQL](../sql/reference.sql) and [design rationale](DESIGN_NOTES.md) |
| Check one implementation independently | [Base-R calculations](../R/reference_metrics.R) |
| Support use in another team's pipeline | [Version-bound verifier and GitHub Action](VERIFY_SUITE.md) |
| Credit the implementation process honestly | [Contributor pull request #8](https://github.com/dfrbagley-cpu/health-data-edge-cases/pull/8) and [commit history](https://github.com/dfrbagley-cpu/health-data-edge-cases/commits/main/) |

**Next evidence to earn.** A maintainer outside this repository uses one case to
check their own synthetic transformation, explains a discrepancy, and repeats
the check after a change. That is a more useful adoption signal than a passing
reference suite alone.

[Run the example](../README.md#see-a-plausible-result-fail) · [Back to the repository](../README.md)
