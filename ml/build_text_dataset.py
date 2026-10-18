#!/usr/bin/env python3
"""Build the ScamLens text dataset from real, freely available corpora + our own
hand-reviewed synthetic multilingual set.

Sources
-------
1. UCI SMS Spam Collection (Almeida et al., 2011) — 5,574 English SMS, ham/spam.
   https://archive.ics.uci.edu/dataset/228/sms+spam+collection
   Mirror used: raw TSV in the public `justmarkham/pycon-2016-tutorial` repo.
2. SpamAssassin public corpus (Apache Software Foundation, public domain) —
   501 spam + 2,501 easy-ham emails.
   https://spamassassin.apache.org/old/publiccorpus/
3. data/synthetic/*.jsonl — ScamLens-authored Bangla / English / Hindi / Urdu
   examples (scam + legitimate), written by the team, reviewed by hand, with a
   `pattern` label linking each scam message to the curated pattern library.

Output: data/processed/{train,val,test}.csv  (columns: text,label,language,source,pattern)
        data/processed/DATASET_CARD.md   (real counts, generated from the data)
"""
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw"
SYNTH = REPO / "data" / "synthetic"
OUT = REPO / "data" / "processed"
SEED = 20261017
random.seed(SEED)

WS = re.compile(r"\s+")
EMAIL_HEADER = re.compile(r"^(?:From|To|Subject|Date|Message-ID|MIME-Version|Content-Type|"
                          r"Content-Transfer-Encoding|Reply-To|Return-Path|Received|X-[\w-]+)\s*:", re.I)


def clean(text: str, limit: int = 900) -> str:
    text = text.replace("\r", " ").replace("\n", " ")
    text = WS.sub(" ", text).strip()
    return text[:limit]


def load_sms() -> list[dict]:
    path = RAW / "sms_spam.tsv"
    rows: list[dict] = []
    if not path.exists():
        print(f"  ! missing {path}")
        return rows
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if "\t" not in line:
                continue
            label, text = line.split("\t", 1)
            label = label.strip().lower()
            if label not in ("ham", "spam"):
                continue
            rows.append({
                "text": clean(text), "label": 1 if label == "spam" else 0,
                "language": "en", "source": "uci_sms_spam", "pattern": None,
            })
    return rows


def _read_mail(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    body_lines = [ln for ln in raw.splitlines() if not EMAIL_HEADER.match(ln)]
    return clean(" ".join(body_lines))


def load_spamassassin() -> list[dict]:
    rows: list[dict] = []
    for folder, label, source in (("sa_spam", 1, "spamassassin_spam"), ("sa_ham", 0, "spamassassin_ham")):
        base = RAW / folder
        if not base.exists():
            print(f"  ! missing {base}")
            continue
        for file in sorted(base.rglob("*")):
            if file.is_file() and not file.name.startswith("cmds"):
                text = _read_mail(file)
                if len(text) >= 25:  # drop empty bodies
                    rows.append({"text": text, "label": label, "language": "en",
                                 "source": source, "pattern": None})
    return rows


def load_synthetic() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(SYNTH.glob("*.jsonl")):
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                rows.append({
                    "text": clean(obj["text"]),
                    "label": 1 if obj["label"] == "scam" else 0,
                    "language": obj.get("language", "en"),
                    "source": "scamlens_synthetic",
                    "pattern": obj.get("pattern"),
                    "_file": path.name,
                    "_line": i,
                })
    return rows


def dedupe(rows: list[dict]) -> tuple[list[dict], int]:
    seen: set[str] = set()
    out: list[dict] = []
    removed = 0
    for r in rows:
        key = WS.sub(" ", r["text"].lower()).strip()
        if not key or len(key) < 8 or key in seen:
            removed += 1
            continue
        seen.add(key)
        r["_key"] = key
        out.append(r)
    return out, removed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading corpora…")
    synthetic = load_synthetic()
    sms = load_sms()
    spam = load_spamassassin()
    print(f"  synthetic={len(synthetic)} sms={len(sms)} spamassassin={len(spam)}")

    rows, removed = dedupe(synthetic + sms + spam)
    print(f"  after dedupe: {len(rows)} (removed {removed} duplicates/empties)")

    df = pd.DataFrame(rows)
    df = df.drop(columns=[c for c in ("_file", "_line", "_key") if c in df.columns])

    # Stratified split by (label, source) so every source and both classes appear
    # in train/val/test, and the multilingual synthetic set is represented in all.
    rng = random.Random(SEED)
    train, val, test = [], [], []
    for (label, source), group in df.groupby(["label", "source"], dropna=False):
        idx = list(group.index)
        rng.shuffle(idx)
        n = len(idx)
        n_val = max(1, int(n * 0.15))
        n_test = max(1, int(n * 0.15))
        val += idx[:n_val]
        test += idx[n_val:n_val + n_test]
        train += idx[n_val + n_test:]

    split_df = {"train": df.loc[train].sample(frac=1, random_state=SEED),
                "val": df.loc[val].sample(frac=1, random_state=SEED),
                "test": df.loc[test].sample(frac=1, random_state=SEED)}
    for name, part in split_df.items():
        part.to_csv(out_dir / f"{name}.csv", index=False)
        print(f"  {name}: {len(part)} rows  (scam={int(part.label.sum())}, ham={int((part.label == 0).sum())})")

    # ---- Dataset card with REAL numbers ----
    lang_counts = df.groupby(["language", "label"]).size().unstack(fill_value=0).to_dict()
    src_counts = df.groupby(["source", "label"]).size().unstack(fill_value=0)
    card = [
        "# ScamLens text dataset card",
        "",
        f"Built by `ml/build_dataset.py` on {pd.Timestamp.utcnow().strftime('%Y-%m-%d %H:%M UTC')} "
        f"with seed {SEED}. Counts below are generated from the actual data.",
        "",
        "## Sources (all freely usable for research)",
        "",
        "| Source | License / terms | Rows kept | scam | legit | Used for |",
        "|---|---|---|---|---|---|",
        f"| UCI SMS Spam Collection | CC BY 4.0 (UCI ML repo #228) | {(df.source == 'uci_sms_spam').sum()} | "
        f"{int(df[df.source == 'uci_sms_spam'].label.sum())} | "
        f"{int((df[df.source == 'uci_sms_spam'].label == 0).sum())} | English SMS phrasing |",
        f"| SpamAssassin corpus (Spam + easy-ham) | Public domain (Apache) | "
        f"{df.source.isin(['spamassassin_spam', 'spamassassin_ham']).sum()} | "
        f"{int(df[df.source.isin(['spamassassin_spam', 'spamassassin_ham'])].label.sum())} | "
        f"{int((df[df.source.isin(['spamassassin_spam', 'spamassassin_ham'])].label == 0).sum())} | longer email phishing style |",
        f"| ScamLens synthetic multilingual set (authored by the team, hand-reviewed) | CC BY 4.0 (this repository) | "
        f"{(df.source == 'scamlens_synthetic').sum()} | "
        f"{int(df[df.source == 'scamlens_synthetic'].label.sum())} | "
        f"{int((df[df.source == 'scamlens_synthetic'].label == 0).sum())} | Bangla/Hindi/Urdu + South-Asian English scams |",
        "",
        f"Duplicates and empty rows removed: **{removed}**.",
        "",
        "## Language distribution (kept rows)",
        "",
        "| language | legit | scam |",
        "|---|---|---|",
    ]
    for lang, part in df.groupby("language"):
        card.append(f"| {lang} | {int((part.label == 0).sum())} | {int(part.label.sum())} |")
    card += [
        "",
        "## Splits (stratified by label × source)",
        "",
        "| split | rows | scam | legit |",
        "|---|---|---|---|",
    ]
    for name, part in split_df.items():
        card.append(f"| {name} | {len(part)} | {int(part.label.sum())} | {int((part.label == 0).sum())} |")
    card += [
        "",
        "## Known limitations (stated, not hidden)",
        "",
        "* The synthetic multilingual rows are team-authored imitations of real scam messages, not "
        "intercepted real fraud. They cover 22 documented typologies but cannot represent every regional variation.",
        "* UCI SMS Spam and SpamAssassin are English-only and from 2011 and 2003, so their vocabulary is dated.",
        "* Bangla/Hindi/Urdu coverage is far smaller than English; per-language metrics are reported separately in "
        "`ml/artifacts/metrics.json` so the gap is visible instead of averaged away.",
        "* Legitimate business bulk SMS (offers, promotions) is deliberately included as *legit* — ScamLens tries to "
        "flag fraud, not marketing.",
        "",
    ]
    (out_dir / "DATASET_CARD.md").write_text("\n".join(card), encoding="utf-8")
    print(f"\nWrote {out_dir}/{{train,val,test}}.csv and DATASET_CARD.md")


if __name__ == "__main__":
    main()
