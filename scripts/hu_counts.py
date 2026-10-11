#!/usr/bin/env python3
"""Print the number of Markdown files per top-level category directory."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRS = ["alaptorveny", "torvenyek", "torvenyereju-rendeletek", "kormanyrendeletek",
        "miniszteri-rendeletek"]

total = 0
for d in DIRS:
    n = 0
    for dp, _, fns in os.walk(os.path.join(ROOT, d)):
        n += sum(1 for f in fns if f.endswith(".md"))
    total += n
    print("%-26s %6d" % (d, n))
print("%-26s %6d" % ("total", total))
sys.exit(0)
