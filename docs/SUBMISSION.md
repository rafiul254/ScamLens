# Submission pack — NYLP AI Hackathon 2026

---

## Submission template

**Project Name:** ScamLens — an AI agent that checks a scam message, explains it, and teaches the pattern

**Team Name:** _ A_Failure _

**Team Members:** _(Rafiul Islam; the rulebook requires each one to have contributed —
see the Team Contributions table in the README)_

**Measured results (harness on record):**

| What | Result |
|---|---|
| Shipped pipeline, held-out 1,252 messages (`ml/eval_ensemble.py`) | F1 0.966, precision 0.989, recall 0.943 |
| Text classifier alone | F1 0.969 |
| URL decisions on the held-out local set (official domains vs look-alikes) | 100% correct (42/42), 0 false alarms |
| Demo Mode samples behaving as labelled | 12/12 |
| Suites | backend 141 passed · frontend 16 passed (157 total) |
| Live smoke test (`scripts/smoke_test.py`) | see the file; runs against a deployed URL too |

**Known limitations:** the held-out corpus is real-world-imbalanced and 97% English, so the
Bangla/Hindi/Urdu numbers come from curated examples and must be read as pilots; the URL risk
decision is a transparent rule layer because every trained candidate false-alarmed on
official bank domains (measured, documented); screenshot OCR and the agent's reasoning need
`GEMINI_API_KEY` and degrade to the deterministic local agent without it; the LLM-only
benchmark column is empty until someone runs `ml/eval_llm.py` with a key; in-process rate
limiting means a single instance.

**AI tools used:** Google Gemini API (`gemini-3.8-flash`) as an optional runtime component, disclosed in
the README; an AI coding assistant was also used during development, and every output was run,
tested and reviewed by the team before submission (see "AI-usage-policy compliance").
Open-source libraries and datasets are acknowledged in the README and `data/README.md`.

**Problem Statement:**
Mobile-money and messaging fraud is exploding across South Asia and it targets exactly
the people least equipped to judge it: elderly and first-time smartphone users. A fake
bKash/Nagad SMS, a "your KYC expires tonight" threat, a "digital arrest" call, a
work-from-home registration fee. Existing tools answer *spam / not spam*, in English, and
stop there — the person still does not know what happened or what to do, so the same
household falls for the next message.

**Solution Overview:**
ScamLens takes a suspicious message, link, screenshot or voice note — in Bangla, English,
Hindi or Urdu, auto-detected — and returns a plain-language verdict with the exact words
that are dangerous highlighted and explained, ordered next steps, a ready-to-send complaint
for the bank or cyber cell, a forwardable WhatsApp warning for elderly relatives, and a
60-second micro-lesson with a quiz that builds a local "Scam IQ". The verdict comes from a
calibrated ensemble of a locally trained text classifier, a trained lexical link-risk model
and a curated 22-pattern scam library, with a Gemini function-calling agent (≤ 6 steps, 8 tools)
driving the analysis and writing the user-facing content. PII in typed text is redacted in the
browser *and* on the server before it reaches a model. Screenshots are sent to Gemini vision as
uploaded for OCR, so users should crop or blur visible sensitive details first. Google's free-tier
data-use terms may apply to prompts and images; if the API key is missing or the model is
unreachable, a deterministic local agent answers instead and the UI says so.

**Live Demo URL:** _(deploy: frontend on Vercel/Netlify, API on Render/Railway with the
Dockerfile or render.yaml in this repo — see README §Quick start)_

**GitHub Repository URL:** _(push this repository; if private, give the judges access
before the deadline)_

**Demo Video URL:** _(record with the shot list in `docs/DEMO_SCRIPT.md`)_

**AI Tools Used:**
* **Google Gemini API** (`gemini-3.8-flash`) — the optional agent loop with function calling, vision OCR for
  screenshots, and drafting of lessons/complaints/family alerts. The product runs without a key.
  The free tier is rate-limited; Google may use free-tier prompts and uploaded images under its current
  data-use terms. Typed text is PII-redacted before the call, but screenshots should be cropped/blurred first.
* **scikit-learn** — TF-IDF + calibrated logistic regression text classifier; calibrated
  logistic regression link-risk model; ensemble weight/threshold tuning.
* **sentence-transformers** (paraphrase-multilingual-MiniLM-L12-v2) — second text backend;
  trained, benchmarked and selectable via `TEXT_MODEL_BACKEND=embedding`.
* **AI coding assistant** — used to help write code, as permitted by the rulebook's AI
  usage policy. All output was reviewed, run and tested by the team (157 automated tests).
* Datasets: UCI SMS Spam Collection (CC BY 4.0), SpamAssassin public corpus (public
  domain), PhiUSIIL phishing URL dataset (UCI #967, CC BY 4.0), plus 224 hand-reviewed
  synthetic Bangla/Hindi/Urdu/English messages written by the team.

**Known Limitations:**
* Novel wording, image-only scams and phone-call scams can evade detection; a low score is
  not proof of safety.
* Training data is English-heavy, so Bangla/Hindi/Urdu scores are weaker — per-language
  metrics with sample sizes are published on the Benchmark tab, not averaged away.
* Screenshot scanning requires a Gemini API key; without it the app asks the user to
  paste the text rather than guessing.
* The app flags fraud, not marketing, so an aggressive legal promotion may land in the
  SUSPICIOUS band.
* The classifier's threshold deliberately favours precision over recall for the end user's
  comfort — the cost in F1 is printed by the training script.
* LLM-only benchmark numbers are absent until someone runs `ml/eval_llm.py` with a key; we
  chose an empty cell over a fabricated one.

---

## Final checklist (rulebook §18, 10 items)

| # | Item | Status |
|---|---|---|
| 1 | The core app features work | ✅ analysed end-to-end locally in all four languages; 157 automated tests pass |
| 2 | The live demo link works, if required | ⏳ deploy with `vercel.json` / `render.yaml` in this repo, then test in incognito and on a phone |
| 3 | The repository contains the appropriate source code | ✅ `/backend`, `/frontend`, `/ml`, `/data`, `/docs` |
| 4 | The README is complete | ✅ problem, solution, features, tech stack, AI/API usage, setup, architecture (Mermaid), screenshots section, team contributions |
| 5 | No credentials or API keys are exposed | ✅ `.env` is git-ignored, `../.env` holds placeholders only, the frontend bundle contains no keys |
| 6 | The demo video link is accessible | ⏳ record using `docs/DEMO_SCRIPT.md` |
| 7 | Team details are accurate | ⏳ fill in the README table + this file |
| 8 | The official submission form is complete | ⏳ |
| 9 | The project complies with the hackathon rules | ✅ original work built for this hackathon; AI usage disclosed; datasets licensed and acknowledged (see `AI_USAGE` notes below) |
| 10 | All materials submitted before 19 Oct 2026, 23:59 PKT | ⏳ **push before the last hour — late pushes are disqualified** |

---

## Judge-facing 60-second tour

1. **Home** → tap a Demo Mode card ("bKash prize SMS") — no setup, no typing.
2. **Result** → risk gauge, verdict banner, highlighted words with reasons, "what to do now".
3. **Family Mode** → "Share on WhatsApp" opens a pre-filled warning for elderly relatives.
4. **Lesson** → answer the 3 quiz questions; Scam IQ increases.
5. **Evidence / Agent trace** → the ML score, link score, pattern match, Gemini judgement
   and the actual tool calls with timings.
6. **Benchmark** → real numbers, comparison table, limitations.
7. **History** → "Delete all my data" wipes everything for the device.

## Rulebook rule 10 (AI usage policy) — how we comply

* We can explain the architecture, prompts/workflows, model usage and limitations
  (README, `docs/ML_METHODOLOGY.md`, `docs/API.md`, `docs/URL_RULES.md`, and the agent
  trace shown in the UI).
* No impersonation, no fabricated evidence: the synthetic dataset is declared everywhere,
  and the benchmark page refuses to display unmeasured numbers.
* Nothing untested is submitted: 141 backend + 16 frontend tests run in CI.
* Third-party AI APIs are listed above and in the README.


---

## Day-of-submission status

* Repository tree, zip builder (`scripts/make_submission_zip.sh`) and live smoke test
  (`scripts/smoke_test.py`) are in place; the archive is `dist/ScamLens-NYLP-AI-Hackathon-2026.zip`.
* Remaining before the deadline: deploy the frontend (Vercel/Netlify config in the repo),
  deploy the backend (Render/Railway config in the repo), record the 2-minute demo
  (`docs/DEMO_SCRIPT.md`), fill in team name/members, submit the form.
* No commits after 19 Oct 2026 11:59 PM PKT.
