from suite import propagation

DOMAIN, IP, RESOLVERS = "x.org", "1.2.3.4", ("r1", "r2", "r3")


def fake_query(answers):
    """answers: {(resolver, qname): {values}}; a missing key => no answer (like dig)."""

    def q(rip, qname, rdtype="A"):
        return answers.get((rip, qname), set())

    return q


def _answers(resolvers, value):
    return {
        (r, n): {value} for r in resolvers for n in (f"p.{DOMAIN}", DOMAIN)
    }


def _check(answers):
    return propagation.check(
        DOMAIN, IP, query=fake_query(answers), resolvers=RESOLVERS, probe="p"
    )[0]


def test_all_agree():
    assert _check(_answers(RESOLVERS, IP)) is True


def test_majority_agree():
    assert _check(_answers(("r1", "r2"), IP)) is True  # r3 absent -> still 2/3


def test_minority_fails():
    assert _check(_answers(("r1",), IP)) is False


def test_wrong_ip_fails():
    assert _check(_answers(RESOLVERS, "9.9.9.9")) is False
