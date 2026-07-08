import pytest

from suite import dns


def test_records_ipv4_only():
    # Apex holds the address once; a wildcard CNAME -> apex covers subdomains.
    recs = dns.records("assoc.example.org", "203.0.113.10")
    assert [(r.name, r.type, r.value) for r in recs] == [
        ("assoc.example.org", "A", "203.0.113.10"),
        ("*.assoc.example.org", "CNAME", "assoc.example.org."),
        ("assoc.example.org", "CAA", '0 issue "letsencrypt.org"'),
    ]
    assert all(r.ttl == 300 for r in recs)


def test_records_adds_aaaa_at_apex_only():
    # IPv6 adds an apex AAAA; the wildcard stays a single CNAME (covers both families).
    recs = dns.records("x.org", "1.2.3.4", "2001:db8::1")
    types = {(r.name, r.type) for r in recs}
    assert ("x.org", "AAAA") in types
    assert ("*.x.org", "AAAA") not in types
    assert [r.type for r in recs if r.name == "*.x.org"] == ["CNAME"]


def test_records_omits_aaaa_without_ipv6():
    assert not any(r.type == "AAAA" for r in dns.records("x.org", "1.2.3.4"))


def test_records_strips_trailing_dot():
    assert dns.records("x.org.", "1.2.3.4")[0].name == "x.org"


def test_records_validation():
    with pytest.raises(ValueError):
        dns.records("", "1.2.3.4")
    with pytest.raises(ValueError):
        dns.records("x.org", None)


def test_format_table():
    out = dns.format_table(dns.records("x.org", "1.2.3.4"))
    assert "Name" in out and "*.x.org" in out and "letsencrypt.org" in out


def test_format_zone():
    recs = dns.records("assoc.example.org", "1.2.3.4", "2001:db8::1", mail=_mail())
    out = dns.format_zone(recs, "assoc.example.org")
    assert "$ORIGIN assoc.example.org." in out
    assert "$TTL 300" in out
    # Names are relative to the origin: apex -> '@', subdomains stripped of suffix.
    assert "@\t300\tIN\tA\t1.2.3.4" in out
    assert "*\t300\tIN\tCNAME\tassoc.example.org." in out
    assert "mail\t300\tIN\tA\t1.2.3.4" in out  # explicit MX target, not the wildcard
    assert "_dmarc\t" in out and "ownsuite._domainkey\t" in out
    # TXT values are quoted; no SOA/NS (the registrar owns those).
    assert 'IN\tTXT\t"v=spf1' in out
    assert "SOA" not in out and "\tNS\t" not in out


def test_records_omit_mail_by_default():
    # No mailbox -> the record set is base only (A/AAAA/CNAME/CAA).
    assert not any(r.type in ("MX", "TXT") for r in dns.records("x.org", "1.2.3.4"))


def _mail():
    return dns.MailDns(
        mail_host="mail.assoc.example.org",
        spf_include="_spf.tem.scaleway.com",
        dkim_selector="ownsuite",
        dkim_public_key="MIIBIjANBgkq...PUBKEY",
        dmarc_rua="postmaster@assoc.example.org",
    )


def test_mail_records_mx_spf_dkim_dmarc():
    recs = {
        (r.name, r.type): r.value for r in dns.mail_records("assoc.example.org", _mail())
    }
    assert recs[("assoc.example.org", "MX")] == "10 mail.assoc.example.org."
    assert recs[("assoc.example.org", "TXT")] == "v=spf1 include:_spf.tem.scaleway.com ~all"
    assert recs[("ownsuite._domainkey.assoc.example.org", "TXT")] == (
        "v=DKIM1; k=rsa; p=MIIBIjANBgkq...PUBKEY"
    )
    assert recs[("_dmarc.assoc.example.org", "TXT")] == (
        "v=DMARC1; p=quarantine; rua=mailto:postmaster@assoc.example.org"
    )


def test_records_appends_mail_after_base():
    recs = dns.records("assoc.example.org", "1.2.3.4", mail=_mail())
    types = [r.type for r in recs]
    # Base records (A/CNAME/CAA) come first, then the mail records.
    assert types[:3] == ["A", "CNAME", "CAA"]
    assert set(types[3:]) == {"A", "MX", "TXT"}


def test_records_mail_adds_explicit_mail_a():
    # The MX target must not be a CNAME (RFC 2181), so it gets its own A/AAAA
    # instead of the wildcard CNAME.
    recs = dns.records("assoc.example.org", "1.2.3.4", "2001:db8::1", mail=_mail())
    mail_recs = {r.type: r.value for r in recs if r.name == "mail.assoc.example.org"}
    assert mail_recs == {"A": "1.2.3.4", "AAAA": "2001:db8::1"}


def test_dmarc_without_rua():
    m = dns.MailDns("mail.x.org", "spf.x", "ownsuite", "P", dmarc_rua="")
    dmarc = next(r for r in dns.mail_records("x.org", m) if r.name == "_dmarc.x.org")
    assert dmarc.value == "v=DMARC1; p=quarantine"
