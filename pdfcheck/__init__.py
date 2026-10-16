"""PDF Metadata & Compliance Checker."""

__version__ = "1.0.0"

from pdfcheck.checker import CheckResult, check_pdf, load_rules

__all__ = ["CheckResult", "check_pdf", "load_rules", "__version__"]
