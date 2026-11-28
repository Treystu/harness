#!/bin/bash
cd "$(dirname "$0")/../.."
for pair in 9ecc3453:r 918dad1a:s 0319b9f6:t; do
  th="${pair%%:*}"; tag="${pair##*:}"
  echo "=== $th ($tag) $(date +%H:%M:%S) ==="
  ./.venv/Scripts/python.exe .rx/runs/standup.py "$th" 7093818060 "$tag" 2>&1 | tail -3
done
echo "QUEUE-DONE $(date +%H:%M:%S)"
