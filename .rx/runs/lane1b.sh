#!/bin/bash
cd "$(dirname "$0")/../.."
echo "=== 315608d2 (l5) $(date +%H:%M:%S) ==="
./.venv/Scripts/python.exe .rx/runs/standup.py 315608d2 7093818060 l5 2>&1 | tail -3
echo "LANE1-DONE $(date +%H:%M:%S)"
