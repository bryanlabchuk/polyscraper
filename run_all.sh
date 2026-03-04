#!/bin/bash
# Run everything to get the bot working. Execute from project root.
set -e
cd "$(dirname "$0")"

echo "=== 1. Set token allowances (needs POL for gas) ==="
.venv/bin/python set_allowances.py || echo "Allowances failed - run manually if you have POL"

echo ""
echo "=== 2. Verify setup ==="
.venv/bin/python verify_setup.py

echo ""
echo "=== 3. Test order placement ==="
.venv/bin/python minimal_first_order.py

echo ""
echo "=== 4. Launch bot ==="
pkill -f "python main.py" 2>/dev/null || true
.venv/bin/python main.py
