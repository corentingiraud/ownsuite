import pytest

from suite import dns


def test_records_ipv4_only():
    recs = dns.records("assoc.example.org", "203.0.113.10")
    assert [(r.name, r.type, r.value) for r in recs] == [
        ("*.assoc.example.org", "A", "203.0.113.10"),
        ("assoc.example.org", "A", "203.0.113.10"),
        ("assoc.example.org", "CAA", '0 issue "letsencrypt.org"'),
    ]
    assert all(r.ttl == 300 for r in recs)


def test_records_adds_aaaa_with_ipv6():
    types = {(r.name, r.type) for r in dns.records("x.org", "1.2.3.4", "2001:db8::1")}
    assert ("*.x.org", "AAAA") in types
    assert ("x.org", "AAAA") in types


def test_records_omits_aaaa_without_ipv6():
    assert not any(r.type == "AAAA" for r in dns.records("x.org", "1.2.3.4"))


def test_records_strips_trailing_dot():
    assert dns.records("x.org.", "1.2.3.4")[0].name == "*.x.org"


def test_records_validation():
    with pytest.raises(ValueError):
        dns.records("", "1.2.3.4")
    with pytest.raises(ValueError):
        dns.records("x.org", None)


def test_format_table():
    out = dns.format_table(dns.records("x.org", "1.2.3.4"))
    assert "Name" in out and "*.x.org" in out and "letsencrypt.org" in out
