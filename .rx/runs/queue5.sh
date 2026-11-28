#!/bin/bash
cd "$(dirname "$0")/../.."
for pair in 9ecc3453:u4 0319b9f6:w4 0d7e2f37:x4 2ae32937:y4; do
  th="${pair%%:*}"; tag="${pair##*:}"
  echo "=== $th ($tag) $(date +%H:%M:%S) ==="
  ./.venv/Scripts/python.exe .rx/runs/standup.py "$th" 7093818060 "$tag" 2>&1 | tail -3
done
echo "QUEUE-DONE $(date +%H:%M:%S)"
