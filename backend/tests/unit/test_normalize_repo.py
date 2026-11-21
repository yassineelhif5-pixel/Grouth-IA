"""GitHub repo input accepts a full link or owner/name."""
from apps.integrations.providers import normalize_repo


def test_normalize_repo_accepts_url_and_shorthand():
    assert normalize_repo("https://github.com/acme/site") == "acme/site"
    assert normalize_repo("https://github.com/acme/site.git") == "acme/site"
    assert normalize_repo("https://github.com/acme/site/tree/main") == "acme/site"
    assert normalize_repo("git@github.com:acme/site.git") == "acme/site"
    assert normalize_repo("acme/site") == "acme/site"
    assert normalize_repo("  ACME/Site  ") == "ACME/Site"
    assert normalize_repo("") == ""
    assert normalize_repo(None) == ""
