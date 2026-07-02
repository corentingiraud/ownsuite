"""Drift guard for the hand-written shell completions (completions/suite.*).

The completion scripts list the `suite` subcommands by hand; this asserts they
stay in sync with the argparse parser, so adding a verb to suite/cli.py without
updating the completions fails CI instead of silently shipping a stale completion."""

from pathlib import Path

import pytest

from suite.cli import build_parser

COMPLETIONS = Path(__file__).resolve().parent.parent / "completions"


def _subcommands():
    """Top-level subcommand names, straight from the parser."""
    sub = next(a for a in build_parser()._subparsers._group_actions if a.choices)
    return set(sub.choices)


@pytest.mark.parametrize("script", ["suite.bash", "suite.zsh"])
def test_completion_lists_every_subcommand(script):
    text = (COMPLETIONS / script).read_text()
    missing = [c for c in _subcommands() if c not in text]
    assert not missing, f"{script} is missing subcommands: {sorted(missing)}"
