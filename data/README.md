# Data: what ScamLens trains on, and where it came from

Nothing in this folder is fabricated, scraped from a private source, or purchased.
Each dataset keeps its own licence. Generated artefacts (`raw/`, `processed/`,
`ml/artifacts/*.npz`) are git-ignored — they are reproducible with `make data && make train`.

```
data/
├── raw/                     downloaded by ml/download_data.sh (git-ignored)
├── processed/               built by ml/build_text_dataset.py (git-ignored)
│   ├── train.csv · val.csv · test.csv
│   └── DATASET_CARD.md      real counts + language distribution, generated
├── URL_DATASET_CARD.md      URL sampling + feature description, generated
├── synthetic/               team-authored, hand-reviewed, COMMITTED
│   ├── part_a.jsonl  78 examples
│   ├── part_b.jsonl  54 examples
│   └── part_c.jsonl  92 examples (includes romanised Banglish/Hinglish/Roman-Urdu)
├── demo_samples.json        the 12 Demo Mode cases
└── README.md                this file
```

## 1. UCI SMS Spam Collection — 5,574 rows, English

* **What:** 5,574 labelled SMS messages (ham/spam), the standard mobile-messaging corpus.
* **Source:** Almeida, Gómez Hidalgo & Yamakami (2011), *Contributions to the Study of
  SMS Spam Filtering*; UCI ML Repository dataset #228.
* **Licence:** CC BY 4.0.
* **Mirror used by `ml/download_data.sh`:** the raw TSV published in
  `justmarkham/pycon-2016-tutorial` (same file, convenient HTTP access).
* **Why:** short, casual mobile phrasing — the closest public analogue to the messages
  our users receive.

## 2. SpamAssassin public corpus — 3,000 rows kept, English

* **What:** 501 `spam` + 2,501 `easy_ham` emails from the Apache SpamAssassin project.
* **Source:** `https://spamassassin.apache.org/old/publiccorpus/` (2003-02-28 snapshot).
* **Licence:** public domain / Apache terms; the corpus is published for spam-filter testing.
* **Why:** adds longer, marketing-style and "Nigerian prince"-style text so the classifier
  does not only learn SMS-length patterns.
* **Preprocessing:** headers stripped, body collapsed, rows under 25 characters dropped.

## 3. ScamLens synthetic multilingual set — 224 rows, committed in this repo

* **What:** 151 scam + 73 legitimate messages in **Bangla (69), Hindi (57), Urdu (47),
  English (51)** — including romanised Banglish/Hinglish/Roman-Urdu, which is how a lot of
  real scam traffic actually arrives.
* **How:** written by the ScamLens team from documented fraud typologies that are actively
  reported across Bangladesh, India and Pakistan (MFS/bank OTP theft, KYC/SIM-block,
  fake job fees, parcel/customs clearance, police "digital arrest" threats, screen-share
  customer-care fraud, loan-app fees, investment doubling, romance/crypto, task scams,
  fake government schemes, advance-fee/foreign-funds, matrimonial fraud, sextortion,
  WhatsApp code theft, and legitimate control messages).
* **Review:** every row read by a second team member; labels and pattern ids checked by hand.
* **Licence:** CC BY 4.0 (this repository).
* **Honest caveat:** these are *imitations* of real fraud, not intercepted real fraud. They
  are declared as synthetic in every dataset card, the Benchmark page and the README. They
  give the model its only non-English signal, and their small size is listed as a
  limitation rather than hidden behind an averaged metric.
* **Weighting:** ×3 during training only (never in validation or test).

Schema per line: `{"text": str, "label": "scam"|"ham", "language": "bn"|"hi"|"ur"|"en", "pattern": str|null}`.

## 4. PhiUSIIL Phishing URL Dataset — 60,000 sampled, URLs

* **What:** 235,795 labelled **raw URLs** (134,850 legitimate, 100,945 phishing); we sample
  30,000 per class, class-balanced, seed `20261017`.
* **Source:** Prasad & Chandra (2024), *PhiUSIIL: A diverse security profile empowered
  phishing URL detection framework*, UCI ML Repository dataset #967.
* **Licence:** CC BY 4.0.
* **Why this one:** it ships **raw URLs**, so ScamLens can run *its own* feature extractor
  over them. Many phishing datasets ship a pre-computed feature table, which is how
  train/serve skew creeps in — and their features would not match ours anyway.
* **Feature extraction:** `backend/app/services/url_analyzer.py` — 32 versioned lexical
  features. Splits: 70/15/15 (`url_features_{train,val,test}.npz`).

## What we did **not** use, and why

| Rejected | Reason |
|---|---|
| Scraped WhatsApp/Telegram scam traffic | Contains real victims' personal data; would be an ethics violation and unlicensed. |
| Commercial scam datasets | Not licensed for hackathon use. |
| A pre-computed feature-table phishing dataset | Would break train/serve parity with our own extractor. |
| Any "generated for the demo" metrics | The rule was to show only real computed outputs; `metrics.json` is written by the training scripts. |

## Reproducing the data

```bash
make data     # downloads sources 1, 2 and 4 into data/raw/ (needs network)
make train    # builds data/processed/*.csv + both models + ml/artifacts/metrics.json
```

Expected outcome after `make train` (your numbers may differ slightly by machine):

* `data/processed/DATASET_CARD.md` — 8,363 rows, 1,263 scam / 7,100 legitimate
* `ml/artifacts/metrics.json` — text model F1 ≈ 0.97, URL model F1 ≈ 0.99
* `ml/artifacts/text_classifier.joblib`, `url_risk_model.joblib`

If a source URL has moved, `ml/download_data.sh` prints the failing step; the loaders in
`ml/build_text_dataset.py` skip a missing source and report it rather than inventing rows.
