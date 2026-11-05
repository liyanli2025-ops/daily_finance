#!/usr/bin/env bash
# Explicit operator action: free tests/preview, then at most ONE charged review.
set -euo pipefail
finance_review_tools=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
finance_review_package=${finance_review_tools%/tools}
cd /var/www/finance-daily/backend
sudo venv/bin/python -m unittest discover \
  -s "$finance_review_package/backend/tests" -p test_saved_editorial.py
sudo venv/bin/python "$finance_review_tools/resume_saved_editorial_review.py"
finance_review_sha=$(sudo venv/bin/python -c 'import json; print(json.load(open("data/diagnostics/saved-editorial-v1/review-continuation/preview.json"))["input_sha256"])')
sudo venv/bin/python -u "$finance_review_tools/resume_saved_editorial_review.py" \
  --run --input-sha "$finance_review_sha"
sudo venv/bin/python "$finance_review_tools/resume_saved_editorial_review.py" \
  --export-review /tmp/daily-finance-editorial-completed-review.zip
