"""Unit tests for `suite dns` (steps.run_dns) + its CLI wiring. No SSH, no
network: the public IP is passed in and config.load_env is faked."""

import argparse

import pytest

from suite import cli, dns, steps
from suite.errors import SuiteError


def _args(**kw):
    base = dict(env_file=".env", domain=None, ssh=None, public_ip=None, out=None)
    base.update(kw)
    return argparse.Namespace(**base)


def test_run_dns_writes_zone_and_prints_table(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(steps.config, "load_env", lambda p: {})
    out = tmp_path / "z.zone"
    steps.run_dns(_args(domain="assoc.example.org", public_ip="203.0.113.10", out=str(out)))
    zone = out.read_text()
    assert "$ORIGIN assoc.example.org." in zone
    assert "@\t300\tIN\tA\t203.0.113.10" in zone
    assert "*\t300\tIN\tCNAME\tassoc.example.org." in zone
    # The copy-paste table is still printed to the console.
    assert "*.assoc.example.org" in capsys.readouterr().out


def test_run_dns_defaults_zone_path_and_reads_domain_from_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(steps.config, "load_env", lambda p: {"OWNSUITE_DOMAIN": "x.org"})
    steps.run_dns(_args(public_ip="1.2.3.4"))
    assert (tmp_path / "x.org.zone").read_text().startswith("$ORIGIN x.org.")


def test_run_dns_requires_domain(monkeypatch):
    monkeypatch.setattr(steps.config, "load_env", lambda p: {})
    with pytest.raises(SuiteError):
        steps.run_dns(_args(public_ip="1.2.3.4"))


def test_run_dns_includes_mail_records_when_mailbox_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(steps.config, "load_env", lambda p: {"OWNSUITE_APP_MESSAGES": "true"})
    monkeypatch.setattr(steps, "_ensure_mail", lambda cfg, domain: dns.MailDns(
        mail_host=f"mail.{domain}", spf_include="spf.example", dkim_selector="ownsuite",
        dkim_public_key="PUBKEY", dmarc_rua="",
    ))
    out = tmp_path / "z.zone"
    steps.run_dns(_args(domain="assoc.example.org", public_ip="1.2.3.4", out=str(out)))
    zone = out.read_text()
    assert "mail\t300\tIN\tA\t1.2.3.4" in zone  # explicit MX target (not the wildcard)
    assert "IN\tMX\t10 mail.assoc.example.org." in zone


def test_dns_subcommand_parses():
    args = cli.build_parser().parse_args(
        ["dns", "--domain", "x.org", "--public-ip", "1.2.3.4", "--out", "/tmp/x.zone"]
    )
    assert args.command == "dns"
    assert (args.domain, args.public_ip, args.out) == ("x.org", "1.2.3.4", "/tmp/x.zone")
