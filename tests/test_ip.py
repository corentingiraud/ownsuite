from suite import ip


def test_parse_global_ipv4():
    out = '[{"addr_info":[{"family":"inet","scope":"global","local":"93.184.216.34"}]}]'
    assert ip.parse_ip_json(out, 4) == "93.184.216.34"


def test_skips_private_address():
    out = '[{"addr_info":[{"family":"inet","scope":"global","local":"10.0.0.5"}]}]'
    assert ip.parse_ip_json(out, 4) is None


def test_skips_link_local_scope():
    out = '[{"addr_info":[{"family":"inet6","scope":"link","local":"fe80::1"}]}]'
    assert ip.parse_ip_json(out, 6) is None


def test_parses_global_ipv6():
    out = '[{"addr_info":[{"family":"inet6","scope":"global","local":"2606:4700:4700::1111"}]}]'
    assert ip.parse_ip_json(out, 6) == "2606:4700:4700::1111"


def test_bad_json_returns_none():
    assert ip.parse_ip_json("not json", 4) is None
