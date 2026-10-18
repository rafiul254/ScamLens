#!/usr/bin/env bash
# Downloads the real, freely-usable datasets ScamLens trains on.
# Nothing here is scraped from a private source, and no dataset is fabricated.
set -euo pipefail
cd "$(dirname "$0")/../data/raw"

echo "1/3 UCI SMS Spam Collection (via the public justmarkham/pycon-2016-tutorial mirror)…"
curl -sSL -o sms_spam.tsv "https://raw.githubusercontent.com/justmarkham/pycon-2016-tutorial/master/data/sms.tsv"
wc -l sms_spam.tsv

echo "2/3 SpamAssassin public corpus (Apache Software Foundation, public domain)…"
curl -sSL -o sa_spam.tar.bz2 "https://spamassassin.apache.org/old/publiccorpus/20030228_spam.tar.bz2"
curl -sSL -o sa_easy_ham.tar.bz2 "https://spamassassin.apache.org/old/publiccorpus/20030228_easy_ham.tar.bz2"
mkdir -p sa_spam sa_ham
tar xjf sa_spam.tar.bz2 -C sa_spam --strip-components=0 2>/dev/null || true
tar xjf sa_easy_ham.tar.bz2 -C sa_ham --strip-components=0 2>/dev/null || true

echo "3/3 PhiUSIIL Phishing URL Dataset (UCI #967, CC BY 4.0)…"
curl -sSL -o phiusiil.zip "https://archive.ics.uci.edu/static/public/967/phiusiil+phishing+url+dataset.zip"

echo "Done. Next: make train"
