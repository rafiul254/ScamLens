#!/usr/bin/env python3
"""Build the URL dataset using ScamLens's OWN feature extractor.

Source: PhiUSIIL Phishing URL Dataset (Prasad & Chandra, 2024; UCI ML repo #967,
CC BY 4.0) — 235,795 labelled raw URLs (134,850 legitimate, 100,945 phishing).
Because the file contains the *raw URLs*, we can run the exact same Python
feature extractor used at inference time. That keeps train/serve parity honest.

Output: ml/artifacts/url_features_{train,val,test}.npz + data/url_dataset_card.md
"""
from __future__ import annotations

import argparse
import random
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services.url_analyzer import FEATURE_ORDER_SOURCE, extract_features  # noqa: E402

RAW = REPO / "data" / "raw"
ARTIFACTS = REPO / "ml" / "artifacts"
SEED = 20261017


def load_urls(sample_per_class: int, seed: int = SEED) -> pd.DataFrame:
    zip_path = RAW / "phiusiil.zip"
    csv_path = RAW / "PhiUSIIL_Phishing_URL_Dataset.csv"
    if zip_path.exists():
        with zipfile.ZipFile(zip_path) as z:
            with z.open("PhiUSIIL_Phishing_URL_Dataset.csv") as fh:
                df = pd.read_csv(fh, usecols=["URL", "label"])
    elif csv_path.exists():
        df = pd.read_csv(csv_path, usecols=["URL", "label"])
    else:
        raise SystemExit(
            "PhiUSIIL dataset not found. Download it first:\n"
            "  curl -sSL -o data/raw/phiusiil.zip "
            "'https://archive.ics.uci.edu/static/public/967/phiusiil+phishing+url+dataset.zip'"
        )
    df = df.dropna().drop_duplicates(subset=["URL"])
    # In PhiUSIIL: label 1 = legitimate, 0 = phishing
    legit = df[df.label == 1]
    phish = df[df.label == 0]
    n = min(sample_per_class, len(legit), len(phish))
    rng = random.Random(seed)
    legit = legit.sample(n=n, random_state=seed)
    phish = phish.sample(n=n, random_state=seed)
    out = pd.concat([legit, phish]).sample(frac=1, random_state=seed).reset_index(drop=True)
    out["y"] = (out.label == 0).astype(int)  # 1 = phishing
    return out


# --- curated local slice ------------------------------------------------------------
# THE PROBLEM THIS FIXES: PhiUSIIL is a global corpus. A scaled linear model trained only
# on it extrapolates badly on URLs from a different population — in testing it returned
# ~0.99 for https://www.bkash.com/terms as well as for a look-alike .tk domain, i.e. it was
# confidently wrong in both directions. The fix is to teach the model OUR population: the
# official domains of the brands we defend (legitimate) and mechanically generated
# look-alikes of those same brands (phishing). Both come from the brand list that already
# ships in backend/app/services/url_analyzer.py, so no new data source is introduced.
OFFICIAL_PATHS = [
    "", "/", "/terms", "/help", "/privacy", "/login", "/signin", "/account", "/support",
    "/en/business", "/personal", "/offers", "/careers", "/faq", "/contact", "/app",
    "/services", "/rates", "/branch-locator", "/download", "/notice", "/about",
]
LOOKALIKE_TLDS = ["tk", "ml", "xyz", "top", "click", "online", "site", "shop", "info", "buzz", "cf", "gq"]
LOOKALIKE_PREFIXES = ["secure-", "verify-", "login-", "kyc-", "update-", "support-", "help-", "-login", "-verify", "-secure", "-support"]
LOOKALIKE_SUFFIXES = ["-secure", "-verify", "-login", "-kyc", "-support", "-update", "-help", "-account", "-service", "-online"]
LOOKALIKE_PATHS = ["/login", "/verify", "/kyc", "/otp", "/account", "/update", "/secure", "/confirm", "/wallet", "/signin"]
LEET = {"a": "4", "e": "3", "i": "1", "o": "0", "s": "5", "b": "8", "g": "9"}


def legit_path_shapes(legit_urls: list[str], per_domain: int = 8, seed: int = SEED) -> list[str]:
    """Path + query shapes taken from *real* legitimate URLs in the corpus.

    Hand-written paths were not enough: a real bank's deep link (/personal/save/accounts)
    still tripped the model, because PhiUSIIL's legitimate class rarely contains
    banking-shaped paths, so the classifier had learnt "sensitive path token => phishing".
    Sampling real path shapes and re-attaching them to our official domains teaches the
    model the truth: legit sites have /account, /login and /verify pages too.
    """
    from urllib.parse import urlsplit

    rng = random.Random(seed)
    shapes, seen = [], set()
    for url in legit_urls:
        try:
            parts = urlsplit(url)
        except ValueError:
            continue
        shape = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        if shape not in seen and 1 < len(shape) <= 90:
            seen.add(shape)
            shapes.append(shape)
    rng.shuffle(shapes)
    return shapes[: per_domain * 40]


def curated_local_urls(legit_urls: list[str] | None = None) -> pd.DataFrame:
    """Legitimate official-domain URLs (y=0) and brand look-alikes (y=1)."""
    from app.services.url_analyzer import BRANDS

    official, lookalike = set(), set()
    shapes = legit_path_shapes(legit_urls or [], per_domain=6)
    for brand, domains in BRANDS.items():
        for domain in domains:
            for path in OFFICIAL_PATHS:
                official.add(f"https://www.{domain}{path}")
                official.add(f"https://{domain}{path}")
            for shape in shapes[:6]:
                official.add(f"https://www.{domain}{shape}")
                official.add(f"https://{domain}{shape}")
            stem = domain.split(".")[0]
            if len(stem) < 4:
                continue
            for tld in LOOKALIKE_TLDS:
                lookalike.add(f"http://{stem}-{LOOKALIKE_PREFIXES[1][:-1]}.{tld}{LOOKALIKE_PATHS[1]}")
                lookalike.add(f"http://{stem}{LOOKALIKE_SUFFIXES[2]}.{tld}{LOOKALIKE_PATHS[0]}")
            for prefix in LOOKALIKE_PREFIXES:
                lookalike.add(f"http://{prefix}{stem}.tk/verify")
                lookalike.add(f"https://{prefix}{stem}.xyz/login")
            for suffix in LOOKALIKE_SUFFIXES:
                lookalike.add(f"http://www.{stem}{suffix}.top/account")
                lookalike.add(f"https://{stem}{suffix}.info/kyc")
            # leetspeak / homoglyph variants
            leet = "".join(LEET.get(ch, ch) for ch in stem)
            if leet != stem:
                lookalike.add(f"http://{leet}-secure.com/login")
                lookalike.add(f"https://{leet}.online/verify")
            lookalike.add(f"http://{domain}.security-check.tk/login")
            lookalike.add(f"https://{stem}.{domain.split('.')[-1]}.verify-account.click/otp")

    from url_sanity_set import EXCLUDED_FROM_TRAINING

    legit = pd.DataFrame({"URL": sorted(official - EXCLUDED_FROM_TRAINING), "y": 0})
    phish = pd.DataFrame({"URL": sorted(lookalike - EXCLUDED_FROM_TRAINING), "y": 1})
    return pd.concat([legit, phish]).sample(frac=1, random_state=SEED).reset_index(drop=True)


def featurise(df: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    order = list(FEATURE_ORDER_SOURCE)
    rows = []
    for url in df.URL.tolist():
        feats = extract_features(str(url)).features
        rows.append([float(feats.get(k, 0.0)) for k in order])
    return np.asarray(rows, dtype=np.float32), order


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample-per-class", type=int, default=30000)
    args = ap.parse_args()

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    df = load_urls(args.sample_per_class)
    print(f"Loaded {len(df)} URLs ({int(df.y.sum())} phishing / {int((df.y == 0).sum())} legitimate)")

    X, order = featurise(df)
    y = df.y.to_numpy()
    # Curated local slice joins the training split only: the held-out test split stays
    # pure PhiUSIIL so the published benchmark numbers remain comparable to earlier runs,
    # while the shipped model also learns the brand population it actually meets.
    local = curated_local_urls(df[df.y == 0].URL.tolist())
    X_local, _ = featurise(local)
    y_local = local.y.to_numpy()
    print(f"curated local slice: {len(local)} URLs ({int(y_local.sum())} look-alikes, "
          f"{int((y_local == 0).sum())} official-domain pages) -> training split only")

    n = len(df)
    idx = np.arange(n)
    rng = np.random.default_rng(SEED)
    rng.shuffle(idx)
    n_train, n_val = int(n * 0.7), int(n * 0.15)
    splits = {
        "train": idx[:n_train],
        "val": idx[n_train:n_train + n_val],
        "test": idx[n_train + n_val:],
    }
    for name, ix in splits.items():
        if name == "train":
            X_split = np.vstack([X[ix], X_local])
            y_split = np.concatenate([y[ix], y_local])
            urls_split = np.concatenate([df.URL.to_numpy()[ix], local.URL.to_numpy()])
        else:
            X_split, y_split, urls_split = X[ix], y[ix], df.URL.to_numpy()[ix]
        np.savez_compressed(ARTIFACTS / f"url_features_{name}.npz", X=X_split, y=y_split,
                            urls=urls_split)
        print(f"  {name}: {len(X_split)} rows ({int(y_split.sum())} phishing)")

    card = REPO / "data" / "URL_DATASET_CARD.md"
    card.write_text(
        "\n".join([
            "# ScamLens URL dataset card",
            "",
            f"Generated by `ml/build_url_dataset.py` on {pd.Timestamp.utcnow().strftime('%Y-%m-%d %H:%M UTC')} "
            f"(seed {SEED}).",
            "",
            "* **Source:** PhiUSIIL Phishing URL Dataset (Prasad & Chandra, 2024), UCI ML Repository #967, CC BY 4.0.",
            "* **Size used:** "
            f"{len(df)} URLs sampled class-balanced ({int(df.y.sum())} phishing, {int((df.y == 0).sum())} legitimate) "
            f"from the full 235,795-row corpus, plus {len(local)} curated local URLs "
            f"({int(y_local.sum())} look-alikes, {int((y_local == 0).sum())} official-domain pages) added to the "
            "training split only — derived from the brand list in `backend/app/services/url_analyzer.py`.",
            "* **Features:** the 27 lexical features computed by `backend/app/services/url_analyzer.py` — the same "
            "code path used in production, so no train/serve skew.",
            "* **Splits:** 70% train / 15% validation / 15% test, shuffled with seed "
            f"{SEED}.",
            "",
            "## Limitations",
            "",
            "* PhiUSIIL URLs were collected in 2023–2024; brand-impersonation patterns for South Asian mobile-money "
            "brands (bKash, Nagad, Easypaisa) are covered by our curated brand list rather than by this corpus.",
            "* The dataset's legitimate class skews to established English-language sites, so the model can be "
            "over-confident on legitimate small local sites — the rule layer (brand whitelist, TLD list) compensates.",
            "* Lead-out guarantee: the URLs in `ml/url_sanity_set.py` are excluded from the curated slice, so that "
            "sanity check stays a held-out measurement.",
            "* The curated local slice was added after a measured failure: with PhiUSIIL alone the model scored "
            "`https://www.bkash.com/terms` at 0.99 (false alarm) and that URL is now in the training split. The "
            "held-out test split is deliberately left as pure PhiUSIIL, so the published metrics do not benefit "
            "from the local slice and remain comparable across runs.",
            "* We never fetch or render the URL during training or inference; only the optional HEAD redirect probe "
            "touches the network at request time.",
        ]),
        encoding="utf-8",
    )
    print(f"Wrote {card}")


if __name__ == "__main__":
    main()
