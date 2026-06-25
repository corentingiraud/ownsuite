"""Installer failure type. The CLI catches it, prints the message, exits 1."""

from __future__ import annotations


class SuiteError(Exception):
    """An operator-facing installer failure (bad config, command, timeout)."""
