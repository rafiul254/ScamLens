# ScamLens — ML methodology

Everything in this document is reproducible with two commands:

```bash
make data     # downloads the real corpora (no synthetic replacement, no scraping)
make train    # builds the datasets, trains both models, tunes the ensemble
```

The numbers quoted below are produced by `ml/train_text_model.py` and
`ml/train_url_model.py` and stored in `ml/artifacts/metrics.json`. The Benchmark
page reads that file — **no metric in the product is typed in by hand.**

---

## 1. Text classifier

### Data

| Source | Licence | Rows used | Role |
|---|---|---|---|
| UCI SMS Spam Collection | CC BY 4.0 | 5,574 | English SMS phrasing (short, South-Asian-relevant style) |
| SpamAssassin public corpus (spam + easy-ham) | Public domain | 3,000 | longer email phishing style |
| ScamLens synthetic multilingual set | CC BY 4.0 (this repo) | 224 | Bangla / Hindi / Urdu (+ romanised) scam & legitimate messages |

After de-duplication the corpus is 8,363 rows: **1,263 scam / 7,100 legitimate**.
The synthetic set is the only non-English signal for the text model, and it is
weighted ×3 during training only (never in validation or test) because it is the
minority class. Exact per-language counts live in `data/processed/DATASET_CARD.md`.

Splits are stratified by **label × source** (70/15/15), so every source and both
classes appear in train, validation and test.

### Models trained

1. **`ml_tfidf`** — TF-IDF over word (1–2) and char_wb (3–5) n-grams → Logistic
   Regression wrapped in `CalibratedClassifierCV` (sigmoid, 3-fold).
2. **`ml_embedding`** — multilingual MiniLM sentence embeddings
   (`paraphrase-multilingual-MiniLM-L12-v2`) → calibrated Logistic Regression.

Both use `class_weight="balanced"` and sample weights.

### Result (held-out test split, scored once)

| Model | Precision | Recall | F1 | ROC AUC |
|---|---|---|---|---|
| TF-IDF + calibrated LR | 0.9548 | 0.9845 | **0.9694** | 0.9979 |
| Multilingual MiniLM + calibrated LR | 0.9389 | 0.8756 | 0.9062 | 0.9941 |

**We ship the TF-IDF backend by default, because it won on the validation split
before the test split was touched.** The embedding backend is still trained, kept
in the artefact, published in the Benchmark comparison and selectable at runtime
with `TEXT_MODEL_BACKEND=embedding`. We are not going to ship the more fashionable
model just because it is fashionable — but we do think the honest comparison is
worth more than a tidy story, so both stay visible and the choice is one env var.

Why does TF-IDF win here? The corpus is dominated by short SMS-style text, where
character n-grams are extremely strong; and the non-English portion (~224 rows) is
too small for an embedding model to show its multilingual advantage. With more
Bangla/Hindi/Urdu data we expect that ranking to flip, and the pipeline is already
in place for it.

### Per-language behaviour

Single-language buckets in the test split are small, so the published table
includes a pooled **bn+hi+ur** row next to the per-language rows, each with its
`n`. See `models.ensemble.per_language` in `metrics.json`. This is a small-sample
result and is labelled as such on the Benchmark page.

### Explainability

Embedding models cannot be attributed per token, so explanations come from the
linear TF-IDF surrogate that is trained on the same data and stored in the same
artefact: `contribution = tfidf_value × coefficient`, normalised so the largest
absolute value maps to 1.0. Those numbers drive the highlight intensity in the UI.
This is an approximation and is documented as one — the honest claim is "these are
the words the linear surrogate weights most", not "these are the model's causes".

---

## 2. URL risk model

### Data

**PhiUSIIL Phishing URL Dataset** (Prasad & Chandra, 2024; UCI ML repository #967,
CC BY 4.0): 235,795 labelled **raw URLs**. We sample 60,000 class-balanced and run
**ScamLens's own feature extractor** over them, so training and serving use literally
the same code path — no train/serve skew, which is the usual failure mode when a
dataset ships a pre-computed feature table (as many phishing datasets do).

### Features (32, versioned in `FEATURE_ORDER_VERSION`)

Length/entropy/subdomain depth, digit & hyphen ratios, IP-as-host, `@` in host,
percent-encoding, port, HTTPS, query-parameter count, suspicious-TLD membership,
shortener membership, free-hosting membership, dangerous file extensions, hex blobs,
and **brand impersonation**: edit-distance typosquats, homoglyph substitution
(`paypa1` → `paypal`), brand-in-subdomain/hyphen (`bkash-verify.xyz`) and
brand+keyword combos, checked against a curated list of ~50 banks, MFS providers
and platforms relevant to Bangladesh, India and Pakistan.

### Training and result

Standardised features → calibrated Logistic Regression. An optional XGBoost
comparison is trained when `xgboost` is installed. Selection is by validation F1.

| Model | Precision | Recall | F1 | ROC AUC |
|---|---|---|---|---|
| logreg_calibrated | 0.9903 | 0.9971 | **0.9937** | 0.9977 |

(n = 9,000 held-out URLs; full confusion matrix in `url_metrics.json`.)

This number is high because lexical features are genuinely strong for *URL*
classification, and because the negative class comes from one well-curated corpus.
It is **not** evidence that ScamLens catches phishing in general — a brand-new
look-alike domain with no obvious lexical tells can still score low, which is why
the rule layer, the pattern library and the agent exist on top of it.

### Inference-time behaviour

* The trained model's probability is used when the artefact is present.
* Without the artefact the API falls back to the transparent hand-weighted rule
  score in `_rule_score()` and says `"score_source": "rule_based"` — it never
  pretends to be the model.
* An optional **HEAD-only** redirect probe (3 s timeout, max 4 hops, SSRF-guarded
  against private IPs) can raise the score when a link bounces across domains or
  lands on a brand look-alike. The page is never fetched, parsed or rendered.

---

## 3. The ensemble

```
final_risk = Σ wᵢ · sᵢ   over the signals that are available
```

* signals: `ml` (text classifier probability), `url` (max URL score in the message),
  `pattern` (pattern-library match strength), `llm` (the agent's own judgement).
* **Missing signals are renormalised away, not treated as zero.** A message with no
  link does not get a free "safe" boost.
* Weights and thresholds are grid-searched on the **validation** split only; the test
  split is scored once, after the search.
* The LLM weight is set as a **prior** (0.15) rather than tuned, because tuning it
  would require an API budget to label the whole validation split. `ml/eval_llm.py`
  exists for exactly that, and the Benchmark page shows "not evaluated" until it is
  run rather than inventing a number.

### Constrained thresholds (deliberate false-negative trade-off)

An unconstrained F1 search drives the SCAM threshold down to ~0.25 on this
imbalanced corpus, which would make the app shout "scam" at merely odd messages.
False alarms terrify the exact users this product serves, so the SCAM threshold is
**floored at 0.55** and the SUSPICIOUS band is derived from it. The training script
prints the F1 cost of that constraint next to the unconstrained value, so the
trade-off is visible instead of hidden.

### Why the ensemble decides, not the model

The agent's verdict is the calibrated ensemble. The model's own judgement enters as
one weighted signal (and its raw verdict is shown to the user when it disagrees).
This means no single cleverly-worded message can talk the product into "SAFE", and
no single model failure can produce a confident "SCAM" on its own.

---

## 4. What we did *not* do

* No fabricated data. The synthetic set is declared as synthetic everywhere it
  appears, including the dataset card and the Benchmark page.
* No metric typed into the frontend. The UI reads `metrics.json` through
  `GET /api/benchmark` and renders an honest empty state when it is missing.
* No claim that ~0.97 F1 means the product is "97 % accurate" in the real world.
  The Limitations list on the Benchmark page says the opposite.


---

## Update: what we measured, and what we changed as a result

Everything below was measured with the scripts in this repository, not estimated.

### 1. The shipped pipeline, scored end to end

`ml/eval_ensemble.py` calls the real agent once per held-out row — PII redaction, classifier,
pattern matcher, URL analyser, actionability check, thresholds — so the published number is
what a user receives rather than what the model would do on its own:

| Configuration | Precision | Recall | F1 | ROC AUC |
|---|---|---|---|---|
| ML-only (calibrated TF-IDF) | 0.955 | 0.985 | 0.969 | 0.998 |
| Shipped pipeline (playbook override off) | 0.989 | 0.943 | 0.966 | 0.984 |
| Shipped pipeline (market configuration) | 0.989 | 0.943 | 0.966 | 0.984 |

The pipeline trades 3.4 points of recall for 3.4 points of precision against ML-only: it is
more careful about what it calls fraud, which is the correct bias for a tool that tells people
to stop trusting a message.

### 2. The curated playbook override changes nothing on this corpus

The override (a high-severity, multi-keyword MFS / OTP / fake-authority match outranks the
statistical score) changed **0 of 1,252** held-out decisions. The held-out corpus is UCI SMS
Spam plus SpamAssassin — mostly English SMS and email from 2003–2014 — and contains none of
the South-Asian playbooks the rule exists for. We report the zero rather than implying a
benefit; the rule's effect is visible on the Bangla / Hindi / Urdu demo messages.

### 3. The URL model does **not** decide URL risk, and here is why

The PhiUSIIL-trained link model is excellent on PhiUSIIL's global URL population (F1 0.988)
and unusable on ours. Measured on a held-out local set of official domains and brand
look-alikes (`ml/url_sanity_set.py`, excluded from training):

| Candidate | PhiUSIIL test F1 | Local sanity accuracy | False alarms on official domains |
|---|---|---|---|
| logreg, all 32 features | 0.988 | 69.0% | 12 |
| logreg, host-level features only (27) | 0.982 | 73.8% | 10 |
| xgboost (optional dependency) | 0.995 | 66.7% | 14 |
| **Curated rule layer (shipped)** | n/a | **100%** | **0** |

The failure mode is instructive: PhiUSIIL's legitimate class contains very few banking-shaped
paths, so the model learnt "sensitive path token ⇒ phishing" and flagged
`https://www.hdfcbank.com/personal/save/accounts`. We tried three remedies before giving up on
it: adding curated official-domain and look-alike URLs to training (helped, not enough),
restricting the model to host-level features (helped, not enough), and xgboost (worse on our
population). So the bundle carries `"authoritative": false`; its scores are recorded and
reported, and the transparent rule layer decides. The gate lives in `ml/train_url_model.py`
and refuses to promote a model that false-alarms on the sanity set.

We would rather ship a documented rule that is right than a model that is confidently wrong.

### 4. Two bugs the sanity set caught in the rule layer itself

* `hdfc.bank.in`, `icici.bank.in` and `sbi.bank.in` are the **official** bank domains on a
  registry restricted to RBI-regulated banks, and the redirect probe flagged them as
  look-alikes. Fixed by recognising trusted registries (`.bank.in`, `.gov.*`, `.nic.in`, …).
* A bare-link submission had its text signal set to 0.0 rather than excluded, which let a weak
  "contains a link" pattern dilute strong URL evidence (a look-alike scored 32/100). Fixed by
  excluding the text signal when there is no text, and by letting the URL analyser decide when
  the submission is nothing but a link.

### 5. Thresholds, reconciled

The trainer searches thresholds under the constraint `scam ≥ 0.55`; the constrained optimum is
**suspicious 0.281 / scam 0.625**, and those are the numbers in `metrics.json`, baked into the
model bundle and used by the API and by the Benchmark tab. The trainer reports the
unconstrained optimum alongside them (validation F1 0.9558 unconstrained vs 0.9428 constrained)
so the cost of that safety choice is visible rather than hidden.

### 6. Actionability: a scam must ask for something

Before a verdict is final, the agent checks whether the message actually requests money, a
code, a click, an install, a callback or a KYC/verification step. If it requests nothing and
carries no link or contact, the risk is capped inside the SAFE band and the result is never
reported as a scam — which is why a normal family message mentioning a hospital is not
accused of fraud. The check, the requests it found and whether the cap fired are all returned
in `evidence.actionability`.

The request patterns pair a verb with its object (single nouns like "payment" fire on
legitimate notifications), match on Unicode word boundaries, and skip negated or self-service
contexts: "Share your OTP with our officer" is an ask, "Staff will never ask for your OTP, call
the number printed on your card" is not. This tuning came from testing ten benign messages
(bank alerts, OTP-safety warnings, a family message) and nine scams in four scripts; all ten
benign messages land in SAFE and all nine scams are still caught.
