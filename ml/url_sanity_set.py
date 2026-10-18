"""Local URL sanity set: the check the PhiUSIIL benchmark cannot give us.

PhiUSIIL measures URLs from a global population. It says nothing about whether ScamLens
labels *our* users' URLs correctly — a real bank's deep link or a look-alike of a South
Asian mobile-money brand. This list is that check, and it is deliberately kept out of the
URL training data (see `curated_local_urls()` in build_url_dataset.py, which excludes these
exact strings) so it stays an honest held-out evaluation.

`ml/eval_url_sanity.py` scores this list with the shipped bundle and writes the result into
`ml/artifacts/url_metrics.json`; `backend/tests/test_url_sanity.py` asserts the same
properties through the full agent so a regression fails CI.
"""
from __future__ import annotations

# (url, note) — legitimate: official domains of the brands we defend, with the kind of
# deep paths and query strings real sites use.
LEGIT: list[tuple[str, str]] = [
    ("https://www.bkash.com/terms", "official bKash terms page"),
    ("https://www.bkash.com/en/business", "official bKash business section"),
    ("https://www.bkash.com/products/merchant-payment", "deep path, hyphen in path"),
    ("https://www.nagad.com.bd/help", "official Nagad help page"),
    ("https://www.nagad.com.bd/personal/accounts/statement", "banking-shaped deep path"),
    ("https://www.rocket.com.bd/agent-locator", "official DBBL Rocket page"),
    ("https://www.paypal.com/signin", "official PayPal sign-in"),
    ("https://www.paypal.com/in/webapps/mpp/account-selection", "long legitimate path"),
    ("https://www.hdfcbank.com/personal/save/accounts", "official bank, accounts path"),
    ("https://www.hdfcbank.com/personal/pay/cards/credit-cards", "official bank, credit cards"),
    ("https://www.icicibank.com/personal-banking/accounts", "official bank, accounts path"),
    ("https://www.sbi.co.in/web/personal-banking/accounts", "official bank, accounts path"),
    ("https://www.google.com/search?q=bkash+helpline", "search query with brand term"),
    ("https://www.daraz.com.bd/catalog/?q=mobile+phone", "marketplace search"),
    ("https://www.grameenphone.com/offers", "official telco offers page"),
    ("https://www.robi.com.bd/personal/prepaid", "official telco prepaid page"),
    ("https://ekpay.gov.bd/", "government payment portal"),
    ("https://www.prothomalo.com/bangladesh", "news site section"),
    ("https://www.prothomalo.com/business/banks", "news site deep path"),
    ("https://www.easypaisa.com.pk/", "official Easypaisa home"),
    ("https://www.jazzcash.com.pk/customer-support", "official JazzCash support"),
    ("https://www.bracbank.com/en/personal-banking/cards", "official bank, long path"),
]

# (url, note) — look-alikes of those same brands: the fraud families we actually see.
PHISH: list[tuple[str, str]] = [
    ("http://bkash-verify-login.tk/account", "brand in hyphenated host, abused TLD"),
    ("http://nagad-kyc-verify-customer.top/login", "brand + KYC lure on a cheap TLD"),
    ("https://secure-bkash.xyz/otp", "brand + 'secure' prefix, abused TLD"),
    ("http://easypaisa-support.top/verify", "support lure, abused TLD"),
    ("https://paypa1-secure.com/login", "leet-speak (digit one) look-alike"),
    ("https://www.bkash.net.security-check.info", "brand as subdomain of a look-alike"),
    ("http://rocket-dbbl-bonus.ml/claim", "brand pair + bonus lure"),
    ("http://upay-cashback-offer.ga/", "cashback lure on free TLD"),
    ("https://jazzcash-verify-account.click/login", "brand + verify on a cheap TLD"),
    ("http://paytm-kyc-update.buzz/", "KYC lure on a cheap TLD"),
    ("https://phonepe-cashback.gq/claim", "cashback lure on free TLD"),
    ("http://sbi-secure-login.cf/", "bank impersonation on a free TLD"),
    ("http://hdfcbank-netbanking.xyz/login", "bank + netbanking lure"),
    ("https://icici-verify.top/account", "bank + verify on a cheap TLD"),
    ("http://www.bracbank-update-kyc.online/", "bank + KYC on a cheap TLD"),
    ("https://daraz-lucky-draw.shop/win", "shopping draw lure on a cheap TLD"),
    ("http://foodpanda-free-voucher.shop/", "voucher lure on a cheap TLD"),
    ("https://www.paypal-secure-login.info/signin", "paypal look-alike, long host"),
    ("http://bkash.verify-account-user.top/login", "brand in subdomain of a look-alike"),
    ("https://gp-bonus-recharge.click/offers", "telco bonus lure on a cheap TLD"),
]

EXCLUDED_FROM_TRAINING: set[str] = {url for url, _ in [*LEGIT, *PHISH]}
