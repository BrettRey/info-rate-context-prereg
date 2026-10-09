#!/usr/bin/env bash
# Fetch the authors' reference data into data/ref/ (gitignored).
# [withheld: from private correspondence with the paper's authors]
# [withheld: from private correspondence with the paper's authors]
set -euo pipefail
SHA=f8f509b2af81eb33495260f3c783c09feb75710e   # last push 2019-06-23
BASE="https://raw.githubusercontent.com/keruiduo/SupplMatInfoRate/$SHA"
DEST="$(cd "$(dirname "$0")/.." && pwd)/data/ref"
mkdir -p "$DEST"
for f in InfoRateData.csv InfoRate.Rmd AutomaticSylDetect.csv; do
  curl -fsSL "$BASE/$f" -o "$DEST/$f"
  shasum -a 256 "$DEST/$f"
done
