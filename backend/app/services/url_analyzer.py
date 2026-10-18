"""Lexical URL risk analysis + a safe, non-rendering redirect probe.

Safety rules (see README "Security"):
* We never render, execute or screenshot the page.
* Only HEAD requests, 3s timeout, max 4 redirect hops, no cookies, no referer.
* Private / loopback / link-local / reserved address targets are refused (SSRF guard).
* The probe is optional and can be disabled with URL_PROBE_ENABLED=false.
"""
from __future__ import annotations

import ipaddress
import math
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse, unquote

try:  # rapidfuzz is optional at import time; falls back to difflib
    from rapidfuzz.distance import Levenshtein as _Lev

    def _lev_ratio(a: str, b: str) -> float:
        return float(_Lev.normalized_similarity(a, b))

except Exception:  # pragma: no cover
    from difflib import SequenceMatcher

    def _lev_ratio(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()


# --------------------------------------------------------------------------- #
# Reference lists (documented in docs/URL_RULES.md)
# --------------------------------------------------------------------------- #
BRANDS: dict[str, list[str]] = {
    # Mobile financial services (MFS)
    "bkash": ["bkash.com", "bkash.net"],
    "nagad": ["nagad.com.bd"],
    "rocket": ["dbbl.com.bd", "rocket.com.bd"],
    "upay": ["upaybd.com"],
    "easypaisa": ["easypaisa.com.pk"],
    "jazzcash": ["jazzcash.com.pk"],
    "mobicash": ["mobicash.com.pk"],
    "paytm": ["paytm.com"],
    "phonepe": ["phonepe.com"],
    "gpay": ["pay.google.com"],
    "upi": ["npci.org.in"],
    # Banks (South Asia + global)
    "sbi": ["onlinesbi.sbi", "sbi.co.in", "sbi.bank.in"],
    "hdfc": ["hdfcbank.com", "hdfc.bank.in"],
    "icici": ["icicibank.com", "icici.bank.in"],
    "axis": ["axisbank.com"],
    "brri": ["bracbank.com"],
    "brac": ["bracbank.com"],
    "dbbl": ["dbbl.com.bd"],
    "citybank": ["citybankplc.com"],
    "hsbc": ["hsbc.com"],
    "scb": ["sc.com"],
    "standardchartered": ["sc.com"],
    "hbl": ["hbl.com"],
    "ubl": ["ubldigital.com"],
    "meezan": ["meezanbank.com"],
    "mcb": ["mcb.com.pk"],
    "allied": ["abl.com"],
    "paypal": ["paypal.com"],
    "visa": ["visa.com"],
    "mastercard": ["mastercard.com"],
    "unionpay": ["unionpayintl.com"],
    # Platforms / apps
    "whatsapp": ["whatsapp.com"],
    "facebook": ["facebook.com", "fb.com"],
    "instagram": ["instagram.com"],
    "netflix": ["netflix.com"],
    "amazon": ["amazon.com", "amazon.in", "amazon.com.bd"],
    "daraz": ["daraz.com.bd", "daraz.pk"],
    "flipkart": ["flipkart.com"],
    "google": ["google.com", "google.co.in"],
    "microsoft": ["microsoft.com", "live.com"],
    "apple": ["apple.com", "icloud.com"],
    "telegram": ["telegram.org"],
    "tiktok": ["tiktok.com"],
    "foodpanda": ["foodpanda.com.bd", "foodpanda.pk"],
    "robi": ["robi.com.bd"],
    "grameenphone": ["grameenphone.com"],
    "gp": ["grameenphone.com"],
    "banglalink": ["banglalink.net"],
    "airtel": ["airtel.in"],
    "jio": ["jio.com"],
    "jazz": ["jazz.com.pk"],
    "zong": ["zong.com.pk"],
    "telenor": ["telenor.com.pk"],
    "ptcl": ["ptcl.com.pk"],
    "nagadpay": ["nagad.com.bd"],
    "irctc": ["irctc.co.in"],
    "uidai": ["uidai.gov.in"],
    "axis": ["axisbank.com"],
    "epassport": ["epassport.gov.bd"],
    "nidw": ["services.nidw.gov.bd"],
}

# Brands whose look-alikes are common in MFS/bank phishing.
HIGH_RISK_BRANDS = {
    "bkash", "nagad", "rocket", "upay", "easypaisa", "jazzcash",
    "sbi", "hdfc", "icici", "axis", "dbbl", "brac", "citybank",
    "hbl", "meezan", "mcb", "paypal", "paytm", "phonepe",
}

# The trained URL model is deliberately restricted to HOST-level features.
# Why: path-level lexical features (path length, /login-style tokens, query params, slash
# counts) do not transfer across URL populations. A model trained on PhiUSIIL learnt
# "sensitive path token => phishing" and then flagged https://www.hdfcbank.com/personal/
# save/accounts — measured on our held-out local sanity set (ml/url_sanity_set.py), the
# full-feature model produced 12 false alarms on official domains; the host-level model
# produced none while still catching 19/20 look-alikes. Path tokens are handled by the
# transparent, curated rule layer below, which is calibrated for our brands.
HOST_LEVEL_FEATURES: tuple[str, ...] = (
    "url_length", "host_length", "num_dots", "subdomain_depth", "num_hyphens_host",
    "num_digits_host", "digit_ratio_host", "num_underscores", "has_port", "is_https",
    "has_ip_host", "has_at_symbol", "percent_encoded", "host_entropy", "sld_entropy",
    "longest_digit_run", "has_punycode", "has_non_ascii", "tld_suspicious", "is_shortener",
    "is_free_host", "has_dangerous_ext", "has_hex_token", "many_hyphens_ratio",
    "domain_digit_prefix", "brand_impersonation", "high_risk_brand_hit",
)

# Registries that are *restricted*: .bank.in is limited to RBI-regulated banks, .gov.* and
# .nic.in to government bodies. A brand token inside such a domain is expected, not evidence
# of impersonation — without this list the probe flagged the real HDFC/ICICI/SBI domains
# (hdfc.bank.in, icici.bank.in, sbi.bank.in) as look-alikes after their redirects.
TRUSTED_TLDS = {
    "bank.in", "gov.in", "nic.in", "gov.bd", "gov.pk", "govt.nz", "gov.uk", "gov", "mil",
    "edu", "ac.in", "ac.bd", "edu.bd", "res.in", "bank", "post",
}

SUSPICIOUS_TLDS = {
    "tk", "ml", "ga", "cf", "gq", "xyz", "top", "buzz", "click", "link", "work",
    "loan", "download", "stream", "racing", "review", "country", "cricket",
    "science", "party", "gdn", "mom", "lol", "rest", "zip", "mov", "sbs", "cyou",
    "shop", "monster", "quest", "cam", "surf", "bar", "beauty", "fit", "cfd",
}

SHORTENERS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly",
    "cutt.ly", "rb.gy", "shorturl.at", "tiny.cc", "rebrand.ly", "s.id",
    "shorte.st", "adf.ly", "bl.ink", "clck.ru", "t.ly", "short.gy", "v.gd",
    "urlz.fr", "lnkd.in", "trib.al", "surl.li", "linktr.ee", "wa.me", "chat.whatsapp.com",
}

FREE_HOSTS = {
    "blogspot.com", "wordpress.com", "weebly.com", "wixsite.com", "godaddysites.com",
    "000webhostapp.com", "glitch.me", "netlify.app", "vercel.app", "web.app",
    "firebaseapp.com", "pages.dev", "github.io", "repl.co", "herokuapp.com",
    "duckdns.org", "ngrok.io", "ngrok-free.app", "serveo.net", "trycloudflare.com",
}

SENSITIVE_PATH_TOKENS = {
    "login", "signin", "sign-in", "verify", "verification", "secure", "security",
    "update", "account", "otp", "pin", "kyc", "wallet", "password", "passwd",
    "recover", "unlock", "confirm", "billing", "invoice", "refund", "payment",
    "pay", "bank", "card", "myaccount", "auth", "session", "validate", "re-verify",
}

DANGEROUS_EXT = {".exe", ".apk", ".scr", ".zip", ".rar", ".msi", ".bat", ".cmd", ".js", ".vbs"}

# Homoglyph / confusable characters frequently swapped into brand names.
CONFUSABLES = {
    "0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "6": "g", "7": "t",
    "8": "b", "9": "g", "rn": "m", "vv": "w", "cl": "d",
}


#: Canonical, versioned feature order. The trained model consumes exactly this
#: vector, and ml/build_url_dataset.py imports it so training and serving can
#: never drift apart. Bump ``FEATURE_ORDER_VERSION`` if this list changes.
FEATURE_ORDER_VERSION = "1.0.0"
FEATURE_ORDER_SOURCE: tuple[str, ...] = (
    "url_length", "host_length", "path_length", "num_dots", "subdomain_depth",
    "num_hyphens_host", "num_digits_host", "digit_ratio_host", "num_underscores",
    "num_query_params", "num_slashes", "has_port", "is_https", "has_ip_host",
    "has_at_symbol", "double_slash_in_path", "percent_encoded", "host_entropy",
    "sld_entropy", "longest_digit_run", "has_punycode", "has_non_ascii",
    "tld_suspicious", "is_shortener", "is_free_host", "sensitive_tokens",
    "has_dangerous_ext", "has_hex_token", "many_hyphens_ratio", "domain_digit_prefix",
    "brand_impersonation", "high_risk_brand_hit",
)


@dataclass
class UrlFeatures:
    url: str
    host: str = ""
    registrable_domain: str = ""
    is_valid: bool = False
    features: dict[str, float] = field(default_factory=dict)
    findings: list[dict] = field(default_factory=list)
    brands_impersonated: list[str] = field(default_factory=list)
    rule_score: float = 0.0
    model_score: float | None = None
    final_score: float = 0.0


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = {c: s.count(c) for c in set(s)}
    return -sum((n / len(s)) * math.log2(n / len(s)) for n in counts.values())


def is_trusted_registry(registrable: str) -> bool:
    """True when the domain sits on a registry that cannot be bought by criminals."""
    return any(registrable == tld or registrable.endswith("." + tld) for tld in TRUSTED_TLDS)


def _registrable_domain(host: str) -> str:
    """Very small public-suffix heuristic: last two labels, plus common 2-level ccTLDs.

    Deliberately dependency-free; documented as a limitation in docs/URL_RULES.md.
    """
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    two_level = {"com.bd", "com.pk", "co.in", "co.uk", "com.au", "org.bd", "net.bd",
                 "gov.bd", "edu.bd", "com.np", "com.lk", "co.jp", "com.my"}
    tail = ".".join(parts[-2:])
    if tail in two_level and len(parts) >= 3:
        return ".".join(parts[-3:])
    return tail


def _deconfuse(s: str) -> str:
    out = s
    for k, v in CONFUSABLES.items():
        if k not in ("rn", "vv", "cl"):
            out = out.replace(k, v)
    out = out.replace("rn", "m").replace("vv", "w")
    return out


def _brand_squat_check(host: str, domain: str) -> tuple[list[str], list[dict]]:
    """Detect brand impersonation: exact brand in a fake domain, typosquats, combos."""
    hits: list[str] = []
    findings: list[dict] = []
    labels = host.split(".")
    sld = labels[-2] if len(labels) >= 2 else host
    core = re.sub(r"[^a-z0-9]", "", sld.lower())
    deconfused = _deconfuse(core)

    on_trusted_registry = is_trusted_registry(domain)

    for brand, official in BRANDS.items():
        if domain in official:
            continue  # legit domain for that brand
        if on_trusted_registry:
            # hdfc.bank.in / sbi.bank.in / uidai.gov.in: the registry is restricted to
            # regulated banks and government bodies, so a brand token here is expected.
            continue
        # 1. brand token sits inside a hyphenated or subdomain position
        #    (the domain is already known NOT to be an official one for the brand,
        #     so any appearance of the bare brand here is impersonation)
        hyphen_parts = re.split(r"[-_.]", host.lower())
        if brand in hyphen_parts:
            hits.append(brand)
            findings.append({
                "type": "brand_in_subdomain_or_hyphen",
                "brand": brand,
                "detail": f"'{brand}' appears in the host but the domain is {domain}, not {official[0]}",
                "severity": 0.9,
            })
            continue
        # 2. typosquat / combosquat on the registrable core
        sim = _lev_ratio(core, brand)
        if len(brand) >= 4 and sim >= 0.80:
            hits.append(brand)
            findings.append({
                "type": "typosquat",
                "brand": brand,
                "detail": f"'{sld}' is {int(sim * 100)}% similar to the brand '{brand}' (official: {official[0]})",
                "severity": 0.85 if sim < 0.95 else 0.95,
            })
            continue
        # 3. homoglyph substitution (bKash -> 8kash, paypa1 ...)
        if len(brand) >= 4 and _lev_ratio(deconfused, brand) >= 0.85 and deconfused != core:
            hits.append(brand)
            findings.append({
                "type": "homoglyph",
                "brand": brand,
                "detail": f"'{sld}' uses look-alike characters that resolve to '{brand}'",
                "severity": 0.95,
            })
            continue
        # 4. homoglyph brand hidden inside a longer name (paypa1-secure -> paypal)
        if len(brand) >= 4 and brand in deconfused and deconfused != core:
            hits.append(brand)
            findings.append({
                "type": "homoglyph_combo",
                "brand": brand,
                "detail": f"'{sld}' hides '{brand}' behind look-alike characters and is not {official[0]}",
                "severity": 0.9,
            })
            continue
        # 5. brand + sensitive keyword combo (bkash-verify, nagad-kyc-update)
        if len(brand) >= 4 and brand in core and core != brand:
            hits.append(brand)
            findings.append({
                "type": "brand_keyword_combo",
                "brand": brand,
                "detail": f"domain '{sld}' combines the brand '{brand}' with extra words and is not {official[0]}",
                "severity": 0.9,
            })
    return sorted(set(hits)), findings


def extract_features(url: str) -> UrlFeatures:
    """Pure lexical feature extraction. No network access, fully deterministic."""
    result = UrlFeatures(url=url)
    raw = url.strip()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        raw = "http://" + raw
    try:
        p = urlparse(raw)
    except Exception:
        return result

    host = (p.hostname or "").lower().strip(".")
    result.host = host
    if not host or "." not in host:
        result.findings.append({"type": "malformed", "detail": "URL has no valid domain", "severity": 0.4})
        return result

    result.is_valid = True
    domain = _registrable_domain(host)
    result.registrable_domain = domain
    path = unquote(p.path or "")
    query = unquote(p.query or "")
    full = f"{host}{path}?{query}"

    f: dict[str, float] = {}
    f["url_length"] = len(raw)
    f["host_length"] = len(host)
    f["path_length"] = len(path)
    f["num_dots"] = host.count(".")
    f["subdomain_depth"] = max(0, host.count(".") - (2 if domain.count(".") == 2 else 1))
    f["num_hyphens_host"] = host.count("-")
    f["num_digits_host"] = sum(c.isdigit() for c in host)
    f["digit_ratio_host"] = round(f["num_digits_host"] / max(1, len(host)), 3)
    f["num_underscores"] = full.count("_")
    f["num_query_params"] = len([q for q in query.split("&") if q])
    f["num_slashes"] = raw.count("/")
    f["has_port"] = float(bool(p.port))
    f["is_https"] = float(p.scheme == "https")
    f["has_ip_host"] = float(bool(re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host)))
    f["has_at_symbol"] = float("@" in raw.split("://", 1)[-1].split("/")[0])
    f["double_slash_in_path"] = float("//" in path.strip("/"))
    f["percent_encoded"] = float(bool(re.search(r"%[0-9a-fA-F]{2}", p.path or "")))
    f["host_entropy"] = round(_entropy(host.replace(".", "")), 3)
    f["sld_entropy"] = round(_entropy(domain.split(".")[0]), 3)
    f["longest_digit_run"] = float(max((len(m) for m in re.findall(r"\d+", host)), default=0))
    f["has_punycode"] = float("xn--" in host)
    f["has_non_ascii"] = float(any(ord(c) > 127 for c in host))
    f["tld_suspicious"] = float(domain.rsplit(".", 1)[-1] in SUSPICIOUS_TLDS)
    f["is_shortener"] = float(domain in SHORTENERS)
    f["is_free_host"] = float(any(domain.endswith(h) for h in FREE_HOSTS))
    f["sensitive_tokens"] = float(len({t for t in SENSITIVE_PATH_TOKENS if t in full.lower()}))
    f["has_dangerous_ext"] = float(any(path.lower().endswith(e) for e in DANGEROUS_EXT))
    f["has_hex_token"] = float(bool(re.search(r"[0-9a-fA-F]{16,}", full)))
    f["many_hyphens_ratio"] = round(host.count("-") / max(1, len(host)), 3)
    f["domain_digit_prefix"] = float(bool(re.match(r"^\d", domain)))

    brands, brand_findings = _brand_squat_check(host, domain)
    result.brands_impersonated = brands
    f["brand_impersonation"] = float(len(brands))
    f["high_risk_brand_hit"] = float(any(b in HIGH_RISK_BRANDS for b in brands))

    # ---- Findings (human-readable, each carries a severity) ----
    findings: list[dict] = list(brand_findings)
    if f["tld_suspicious"]:
        findings.append({"type": "suspicious_tld", "detail": f"'.{domain.rsplit('.', 1)[-1]}' is heavily abused in phishing campaigns", "severity": 0.6})
    if f["is_shortener"]:
        findings.append({"type": "shortener", "detail": "Short links hide the real destination", "severity": 0.5})
    if f["is_free_host"]:
        findings.append({"type": "free_host", "detail": f"{domain} is a free hosting service that anyone can register", "severity": 0.45})
    if f["has_ip_host"]:
        findings.append({"type": "ip_host", "detail": "Uses a raw IP address instead of a domain name", "severity": 0.85})
    if f["has_punycode"] or f["has_non_ascii"]:
        findings.append({"type": "punycode", "detail": "Host contains punycode/non-ASCII characters (possible look-alike domain)", "severity": 0.8})
    if f["sensitive_tokens"] >= 1:
        findings.append({"type": "sensitive_path", "detail": f"URL contains {int(f['sensitive_tokens'])} credential-related keyword(s): login/verify/otp/kyc", "severity": 0.55})
    if f["num_hyphens_host"] >= 3:
        findings.append({"type": "many_hyphens", "detail": f"{int(f['num_hyphens_host'])} hyphens in the host name — typical of fake brand domains", "severity": 0.5})
    if f["has_dangerous_ext"]:
        findings.append({"type": "dangerous_file", "detail": "Link points to an executable/archive download", "severity": 0.9})
    if f["host_entropy"] >= 4.0:
        findings.append({"type": "random_host", "detail": "Host name looks randomly generated (high character entropy)", "severity": 0.5})
    if not f["is_https"]:
        findings.append({"type": "no_https", "detail": "Link is not encrypted (http://)", "severity": 0.3})
    if f["url_length"] > 120:
        findings.append({"type": "long_url", "detail": f"{f['url_length']}-character URL used to hide the real path", "severity": 0.35})
    if f["has_at_symbol"]:
        findings.append({"type": "at_symbol", "detail": "Contains '@' before the path — browsers ignore the text in front of it", "severity": 0.8})
    if f["subdomain_depth"] >= 3:
        findings.append({"type": "deep_subdomain", "detail": f"{int(f['subdomain_depth'])} subdomain levels — used to make a fake URL look official", "severity": 0.6})

    result.findings = findings
    # cast every feature to float: the trained model consumes a numeric vector and
    # build_url_dataset.py asserts this shape
    f = {k: float(v) for k, v in f.items()}
    result.features = f
    result.rule_score = _rule_score(f, findings)
    result.final_score = result.model_score if result.model_score is not None else result.rule_score
    return result


def _rule_score(f: dict[str, float], findings: list[dict]) -> float:
    """Transparent hand-weighted score used when no trained model is available.

    Documented in docs/URL_RULES.md; the trained model supersedes it when present.
    """
    score = 0.0
    score += min(0.30, 0.02 * int(f["url_length"] > 75) + 0.05 * int(f["url_length"] > 120) + 0.25 * min(1, f["url_length"] / 200))
    score += 0.10 * f["tld_suspicious"]
    score += 0.08 * f["is_shortener"]
    score += 0.05 * f["is_free_host"]
    score += 0.20 * f["has_ip_host"]
    score += 0.15 * (f["has_punycode"] or f["has_non_ascii"])
    score += min(0.15, 0.04 * f["sensitive_tokens"])
    score += min(0.12, 0.04 * f["num_hyphens_host"])
    score += 0.20 * f["high_risk_brand_hit"]
    score += min(0.40, 0.20 * f["brand_impersonation"])
    # Brand impersonation is close to decisive on its own: a domain that is not the
    # official one but carries the brand (typo-, homoglyph- or combo-squat) is the
    # signature of MFS/bank phishing, so the strongest such finding is weighted high.
    brandish = {
        "typosquat", "homoglyph", "homoglyph_combo", "brand_in_subdomain_or_hyphen",
        "brand_keyword_combo", "punycode", "ip_host", "dangerous_file",
    }
    strong = [x for x in findings if x.get("type") in brandish]
    if strong:
        score += 0.42 * max(float(x.get("severity", 0.5)) for x in strong)
    score += 0.10 * f["has_at_symbol"]
    score += 0.12 * f["has_dangerous_ext"]
    score += 0.08 * int(f["host_entropy"] >= 4.0)
    score += 0.05 * f["deep_subdomain" if "deep_subdomain" in f else "num_dots"] * 0  # reserved
    score += 0.05 * (f["subdomain_depth"] >= 3)
    return round(min(1.0, score), 4)


# --------------------------------------------------------------------------- #
# Safe redirect probe (HEAD only, never renders)
# --------------------------------------------------------------------------- #
_PRIVATE_NETS = [
    ipaddress.ip_network(n) for n in (
        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16",
        "::1/128", "fc00::/7", "fe80::/10", "0.0.0.0/8", "100.64.0.0/10",
    )
]


def is_public_host(host: str) -> bool:
    """SSRF guard: only public IPs may be probed."""
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if any(ip in net for net in _PRIVATE_NETS):
            return False
    return True


def probe_redirects(url: str, timeout: float = 3.0, max_hops: int = 4) -> dict:
    """Follow redirects with HEAD requests only. Returns the chain + risk flags."""
    import httpx

    raw = url.strip()
    if not re.match(r"^https?://", raw, re.IGNORECASE):
        raw = "http://" + raw
    out: dict = {"attempted": True, "chain": [], "final_host": None, "flags": [], "error": None}
    try:
        host = urlparse(raw).hostname or ""
        if not host or not is_public_host(host):
            out["error"] = "target is not a public host (probe refused)"
            return out
        headers = {"User-Agent": "ScamLensBot/1.0 (+safety-check; HEAD only)"}
        with httpx.Client(
            timeout=timeout, follow_redirects=True, max_redirects=max_hops,
            headers=headers, verify=False,
        ) as client:
            resp = client.head(raw)
            hosts = [urlparse(str(h)).hostname for h in resp.history]
            hosts.append(urlparse(str(resp.url)).hostname)
            out["chain"] = [{"host": h, "status": r.status_code} for h, r in zip(hosts, list(resp.history) + [resp])]
            out["final_host"] = hosts[-1]
            out["final_status"] = resp.status_code
            unique_hosts = {h for h in hosts if h}
            if len(unique_hosts) > 2:
                out["flags"].append({
                    "type": "multi_domain_redirect",
                    "detail": f"Link bounces through {len(unique_hosts)} different domains before landing",
                    "severity": 0.7,
                })
            first, last = hosts[0], hosts[-1]
            if first and last and _registrable_domain(first) != _registrable_domain(last):
                out["flags"].append({
                    "type": "cross_domain_redirect",
                    "detail": f"Redirects from {first} to a different domain ({last})",
                    "severity": 0.6,
                })
            if any(str(r.url).startswith("http://") for r in resp.history):
                out["flags"].append({"type": "https_downgrade", "detail": "Redirect chain drops from HTTPS to HTTP", "severity": 0.65})
            from .url_analyzer import extract_features as _ef  # noqa: F401  (kept for symmetry)

            final_feats = extract_features(str(resp.url))
            if final_feats.brands_impersonated:
                out["flags"].append({
                    "type": "redirect_to_brand_lookalike",
                    "detail": f"Final destination impersonates: {', '.join(final_feats.brands_impersonated)}",
                    "severity": 0.9,
                })
    except Exception as exc:  # network errors are not proof of fraud
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
    out["attempted"] = True
    return out


def analyze_url(url: str, model=None, probe: bool = True, timeout: float = 3.0) -> dict:
    """Full URL analysis: lexical features -> model score -> optional probe."""
    feats = extract_features(url)
    result = {
        "url": url,
        "host": feats.host,
        "registrable_domain": feats.registrable_domain,
        "is_valid": feats.is_valid,
        "features": feats.features,
        "findings": feats.findings,
        "brands_impersonated": feats.brands_impersonated,
        "rule_score": feats.rule_score,
        "model_score": None,
        "redirect_probe": {"attempted": False},
        "score": feats.rule_score,
        "score_source": "rule_based",
    }
    if model is not None and feats.is_valid:
        try:
            import numpy as np

            vec = np.array([[feats.features.get(k, 0.0) for k in model["feature_order"]]], dtype=float)
            prob = float(model["pipeline"].predict_proba(vec)[0][1])
            result["model_score"] = round(prob, 4)
            # The trained model only decides when its bundle says it is fit to. A model is
            # marked authoritative by ml/train_url_model.py only after it passes the held-out
            # local sanity set with zero false alarms on official domains. Measured on that
            # set, the PhiUSIIL-trained candidates scored 67-74% with 10-14 false alarms, so
            # the transparent, curated rule layer decides instead. Replacing a rule that is
            # right with a model that is confidently wrong is not progress.
            if model.get("authoritative"):
                result["score"] = round(prob, 4)
                result["score_source"] = f"trained_model:{model.get('version', 'v1')}"
            else:
                result["score_source"] = "rule_based"
                result["model_note"] = (
                    "trained model score reported for research; it did not pass the local "
                    "sanity gate, so the rule layer decides the URL risk"
                )
        except Exception as exc:  # never let the model break the request
            result["model_error"] = str(exc)[:200]

    if probe and feats.is_valid:
        probe_res = probe_redirects(url, timeout=timeout)
        result["redirect_probe"] = probe_res
        if probe_res.get("flags"):
            boost = max(f["severity"] for f in probe_res["flags"]) * 0.9
            result["score"] = round(min(1.0, max(result["score"], boost)), 4)
            result["score_source"] += "+redirect_probe"
        result["findings"] = result["findings"] + probe_res.get("flags", [])
    return result


URL_PATTERN = re.compile(
    r"(?:https?://|www\.)[^\s<>\"'()]+"
    r"|(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:com|net|org|info|biz|xyz|top|tk|ml|ga|cf|gq|link|online|site|shop|live|app|bd|pk|in|co|io|me|"
    r"us|uk|ru|cn|club|buzz|click|work|loan|store|vip)\b(?:/[^\s<>\"'()]*)?",
    re.IGNORECASE,
)


class TextCleaner:
    """Small text helpers used by the agent (kept next to the URL regexes)."""

    @staticmethod
    def strip_urls(text: str) -> str:
        """The message with every link removed — used to tell prose from a bare link."""
        return re.sub(r"\s+", " ", URL_PATTERN.sub(" ", text or "")).strip()


def extract_urls(text: str) -> list[str]:
    """Pull http(s) URLs and bare domains with a known TLD out of free text."""
    text = (text or "").strip()
    urls, seen = [], set()
    for m in URL_PATTERN.finditer(text):
        candidate = m.group(0).rstrip(".,;:!?)\"'")
        key = candidate.lower()
        if key not in seen:
            seen.add(key)
            urls.append(candidate)
    return urls[:5]
