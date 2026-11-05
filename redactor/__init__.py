"""Redactor package: strips secrets, tokens, passwords, emails, and internal hostnames."""
from redactor.sanitizer import RedactionResult, Redactor

__all__ = ["RedactionResult", "Redactor"]

