"""URL analyzer tests: lexical scoring, brand impersonation, SSRF guard."""
from __future__ import annotations

import pytest

from app.services.url_analyzer import (
    FEATURE_ORDER_SOURCE, analyze_url, extract_features, extract_urls,
    is_public_host, probe_redirects,
)


class TestFeatureExtraction:
    def test_legitimate_url_scores_low(self):
        feats = extract_features("https://www.bkash.com/personal/help")
        assert feats.is_valid
        assert feats.registrable_domain == "bkash.com"
        assert feats.brands_impersonated == []
        assert feats.rule_score < 0.3

    def test_feature_vector_matches_declared_order(self):
        feats = extract_features("https://example.com/a/b?c=d")
        assert set(FEATURE_ORDER_SOURCE).issubset(feats.features.keys())
        for key in FEATURE_ORDER_SOURCE:
            assert isinstance(feats.features[key], float)

    def test_ip_host_and_no_https_are_flagged(self):
        feats = extract_features("http://192.168.10.4/login")
        assert feats.features["has_ip_host"] == 1.0
        assert feats.features["is_https"] == 0.0
        assert any(f["type"] == "ip_host" for f in feats.findings)

    def test_suspicious_tld_and_shortener(self):
        assert extract_features("http://free-data-offer.buzz").features["tld_suspicious"] == 1.0
        assert extract_features("http://bit.ly/x9f2").features["is_shortener"] == 1.0

    def test_punycode_detected(self):
        feats = extract_features("http://xn--80ak6aa92e.com/login")
        assert feats.features["has_punycode"] == 1.0

    def test_bare_domain_is_accepted(self):
        feats = extract_features("bkash-verify.xyz")
        assert feats.is_valid
        assert feats.brands_impersonated


class TestBrandImpersonation:
    @pytest.mark.parametrize(
        "url,brand",
        [
            ("http://bkash-verify-account.xyz/login", "bkash"),
            ("http://nagad.kyc-update.tk", "nagad"),
            ("https://paypa1-secure.com/login", "paypal"),
            ("http://hdfcbank-kyc-verify.cf", "hdfc"),
            ("http://easypaisa-support.top/verify", "easypaisa"),
            ("https://www.bkash.net.security-check.info/otp", "bkash"),
        ],
    )
    def test_lookalike_domains_are_caught(self, url, brand):
        result = analyze_url(url, model=None, probe=False)
        assert brand in result["brands_impersonated"], f"{brand} not caught for {url}"
        assert result["score"] >= 0.5

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.bkash.com",
            "https://www.nagad.com.bd/help",
            "https://www.paypal.com/signin",
            "https://www.hdfcbank.com/personal",
        ],
    )
    def test_official_domains_are_not_flagged(self, url):
        result = analyze_url(url, model=None, probe=False)
        assert result["brands_impersonated"] == [], url
        assert result["score"] < 0.5

    def test_google_search_style_urls_are_not_brands(self):
        result = analyze_url("https://www.google.com/search?q=bkash", model=None, probe=False)
        assert "bkash" not in result["brands_impersonated"]


class TestScoring:
    def test_worse_url_scores_higher(self):
        safe = analyze_url("https://www.dbbl.com.bd/personal", model=None, probe=False)["score"]
        bad = analyze_url("http://dbbl-secure-login-verify.xyz/account/update?a=1&b=2", model=None, probe=False)["score"]
        assert bad > safe
        assert bad >= 0.5

    def test_score_is_bounded(self):
        for url in ["http://a.b", "https://" + "x" * 200 + ".com/" + "y" * 300]:
            score = analyze_url(url, model=None, probe=False)["score"]
            assert 0.0 <= score <= 1.0


class TestExtractUrls:
    def test_extracts_http_and_bare_domains(self):
        text = "Click http://bad-site.tk/login or bkash-verify.xyz now. Thanks."
        urls = extract_urls(text)
        assert "http://bad-site.tk/login" in urls
        assert "bkash-verify.xyz" in urls
        assert len(urls) == 2

    def test_ignores_plain_sentences(self):
        assert extract_urls("Bhai kal office e dekha hobe, 5 tay.") == []

    def test_caps_at_five(self):
        text = " ".join(f"http://site{i}.tk/x" for i in range(9))
        assert len(extract_urls(text)) == 5


class TestSsrfGuard:
    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "10.0.0.5", "192.168.1.1", "169.254.169.254"])
    def test_private_targets_are_refused(self, host):
        assert is_public_host(host) is False

    def test_private_probe_is_skipped(self):
        out = probe_redirects("http://127.0.0.1:8000/admin", timeout=0.5)
        assert out["attempted"] is True
        assert out["chain"] == []
        assert "refused" in (out["error"] or "")

    def test_unresolvable_host_does_not_raise(self):
        out = probe_redirects("http://this-domain-does-not-exist-xyz123.invalid/", timeout=2)
        assert out["error"] is not None
        assert out["chain"] == []
