"""Reference runner for the Health Data Edge Cases conformance suite."""

from .runner import (
    CaseResult,
    CaseValidationResult,
    SuiteResult,
    run_case,
    run_suite,
    validate_case,
)

__all__ = [
    "CaseResult",
    "CaseValidationResult",
    "SuiteResult",
    "run_case",
    "run_suite",
    "validate_case",
]
__version__ = "0.4.0"
