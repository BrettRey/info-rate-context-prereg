#!/usr/bin/env bash
# Fetch the authors' reference data into data/ref/ (gitignored).
# Licences, as stated in the repository's README since commit 70cc011 (2026-10-09; licence
# text added in 00798db): data and the HTML report CC BY 4.0, the R Markdown script the 3-clause
# BSD licence. Fetched at the 2019 commit that Stage 1 used; the three files are
# byte-identical at 00798db.
set -euo pipefail
SHA=f8f509b2af81eb33495260f3c783c09feb75710e   # last push 2019-06-23
BASE="https://raw.githubusercontent.com/keruiduo/SupplMatInfoRate/$SHA"
DEST="$(cd "$(dirname "$0")/.." && pwd)/data/ref"
mkdir -p "$DEST"
for f in InfoRateData.csv InfoRate.Rmd AutomaticSylDetect.csv; do
  curl -fsSL "$BASE/$f" -o "$DEST/$f"
  shasum -a 256 "$DEST/$f"
done
