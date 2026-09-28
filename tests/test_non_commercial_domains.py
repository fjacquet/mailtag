import pytest

from mailtag.utils.domain_utils import load_non_commercial_domains


@pytest.mark.parametrize(
    "domain",
    ["gmail.com", "yahoo.fr", "hotmail.fr", "msn.com", "live.com", "me.com", "gmx.net", "sunrise.ch",
     "hispeed.ch", "vtxnet.ch", "sfr.fr", "bbox.fr", "ljf.ch", "ljfch.onmicrosoft.com"],
)  # fmt: skip
def test_personal_and_own_domains_never_become_domain_rules(domain):
    assert domain in load_non_commercial_domains()


def test_business_domain_is_not_listed():
    assert "bcv.ch" not in load_non_commercial_domains()
