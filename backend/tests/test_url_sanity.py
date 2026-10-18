"""Regression tests for URL risk decisions on the URLs our users actually meet.

These exist because of a real failure: a URL model trained only on PhiUSIIL scored
https://www.bkash.com/terms at 0.99 — a confident false alarm on the real bank's site —
and the same model scored a look-alike at 0.15. The local sanity set (ml/url_sanity_set.py)
is held out of training and is asserted here through the full agent, so any regression in
the rule layer, the brand list or the model gate fails the build.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "ml"))

from url_sanity_set import LEGIT, PHISH  # noqa: E402

from app.deps import build_agent  # noqa: E402
from app.config import get_settings  # noqa: E402


@pytest.fixture(scope="module")
def agent():
    return build_agent(get_settings())


@pytest.mark.parametrize("url,note", LEGIT, ids=[u for u, _ in LEGIT])
def test_official_domains_are_not_reported_as_scams(agent, url, note):
    result = agent.analyze(text=url, device_id="sanity-check", make_lesson=False,
                          make_report=False, make_family_alert=False)
    assert result.evidence.url_score is not None
    assert result.evidence.url_score < 0.5, (url, result.evidence.url_score, note)
    assert result.verdict.value != "SCAM", (url, result.risk_score, note)


@pytest.mark.parametrize("url,note", PHISH, ids=[u for u, _ in PHISH])
def test_brand_look_alikes_are_reported_as_scams(agent, url, note):
    result = agent.analyze(text=url, device_id="sanity-check", make_lesson=False,
                          make_report=False, make_family_alert=False)
    assert result.evidence.url_score is not None
    assert result.evidence.url_score >= 0.7, (url, result.evidence.url_score, note)
    assert result.verdict.value == "SCAM", (url, result.risk_score, note)


def test_url_model_reports_its_own_scores_but_does_not_overrule_the_rules(agent):
    """The bundle carries `authoritative`; until a model passes the sanity gate, the rule
    layer decides. Guard that contract so a future model cannot silently take over."""
    result = agent.analyze(text="https://www.paypal.com/signin", device_id="sanity-check",
                          make_lesson=False, make_report=False, make_family_alert=False)
    bundle = agent.url_model
    assert bundle is not None
    if not bundle.get("authoritative"):
        assert result.evidence.url_score == pytest.approx(
            _rule_score("https://www.paypal.com/signin"), abs=1e-6
        )


def _rule_score(url: str) -> float:
    from app.services.url_analyzer import analyze_url

    return analyze_url(url, model=None, probe=False)["rule_score"]
