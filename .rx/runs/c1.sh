#!/bin/bash
cd "$(dirname "$0")/../.."
echo "=== 315608d2 (c1) $(date +%H:%M:%S) ==="
./.venv/Scripts/python.exe .rx/runs/phase.py 315608d2 7093818060 c1 search,query,select,prepare 2>&1 | tail -3
echo "C1-DONE $(date +%H:%M:%S)"
