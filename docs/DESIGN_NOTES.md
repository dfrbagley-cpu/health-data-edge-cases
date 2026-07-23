# Design notes

## Why tiny cases instead of realistic-scale data?

Scale tests performance. These cases test meaning.

A five-row fixture can make a double-count visible immediately. A million-row synthetic extract may look more realistic while making the same error harder to reason about and easier to dismiss.

## Why CSV?

CSV is unglamorous and broadly usable. Analysts can inspect it in a text editor or spreadsheet, while SQL, R, Python, BI tools, and data platforms can all ingest it. The fixture format should not force adoption of the reference implementation.

## Why SQLite-compatible SQL?

The Python runner uses the standard-library SQLite engine, so a contributor can run the suite without installing packages. The SQL uses window functions and other constructs also supported by DuckDB. It is a readable reference, not a promise that every database can run it unchanged.

## Why a second R implementation?

If expected files and one implementation agree because both contain the same mistake, a test can provide false confidence. The base-R implementation calculates the contract independently and uses no SQL engine. Agreement across the two paths does not prove correctness, but it reduces a meaningful class of reference errors.

## Why are quality signals separate from metrics?

Operational records can be valid evidence for one question and contradictory evidence for another. For example, a completed encounter linked to a cancelled appointment can count as delivered service under this suite's rule while still being flagged for workflow review. Silently choosing only one interpretation destroys useful information.

## What is intentionally absent?

- Authentication, a hosted application, and user accounts
- Realistic clinical narratives
- Official regulatory definitions
- Vendor-specific extraction logic
- AI-generated interpretation
- A comprehensive healthcare common data model

Those additions would create maintenance and governance obligations without improving the initial conformance use case.
