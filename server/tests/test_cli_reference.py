"""Every `maxxing` command and sub-command is listed in the CLI reference (docs/user/17-cli-reference.md)."""
import argparse
import re

from maxxing import cli, config


def _subcommands(parser: argparse.ArgumentParser) -> list[str]:
    for act in parser._actions:
        if isinstance(act, argparse._SubParsersAction):
            return list(act.choices)
    return []


def _listed(doc: str, command: str, word: str) -> bool:
    """`word` appears as a whole word on a line of the reference that names `maxxing <command>`."""
    pat = re.compile(rf"(^|[\s`|/(\\]){re.escape(word)}([\s`|/)\]:,\\]|$)")
    return any(pat.search(line) for line in doc.splitlines() if f"maxxing {command}" in line)


def test_every_cli_command_and_subcommand_is_in_the_reference():
    doc = (config.DOCS_DIR / "17-cli-reference.md").read_text()
    cli._load_plugins()
    missing = []
    for name in ("serve", "setup-link", "password", *cli.COMMANDS):
        if not re.search(rf"maxxing {re.escape(name)}\b", doc):
            missing.append(name)
    for name, (_help, configure, _handler) in cli.COMMANDS.items():
        parser = argparse.ArgumentParser(prog=f"maxxing {name}")
        configure(parser)
        missing += [f"{name} {s}" for s in _subcommands(parser) if not _listed(doc, name, s)]
    assert not missing, f"add to docs/user/17-cli-reference.md: {missing}"
