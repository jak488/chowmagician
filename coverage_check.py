"""Report dietary-restriction coverage in meals.json, by meal slot.

Run:  python3 coverage_check.py [min_per_slot]   (default 7)

A 7-day plan uses 7 breakfasts / 7 lunches / 7 dinners, so a restriction combo needs
at least `min_per_slot` qualifying meals PER SLOT to avoid repeats — and ~10+ to feel
varied across regenerations. This flags every combo/slot below that bar so you know
exactly where to target more generation, instead of guessing.
"""
import json, sys
from itertools import combinations

SLOTS = ("breakfast", "lunch", "dinner")
RESTRICTIONS = ["vegetarian", "vegan", "gluten_free", "dairy_free",
                "heart_healthy", "kidney_healthy"]

# curated combos that matter most (the medically-restrictive / hard ones)
HARD_COMBOS = [
    ("gluten_free", "kidney_healthy"),
    ("gluten_free", "dairy_free", "kidney_healthy"),
    ("heart_healthy", "kidney_healthy"),
    ("dairy_free", "kidney_healthy"),
    ("vegan", "kidney_healthy"),
    ("vegetarian", "gluten_free", "dairy_free"),
    ("vegan", "gluten_free"),
    ("vegan", "heart_healthy"),
]


def counts_by_slot(meals, tags):
    req = set(tags)
    out = {s: 0 for s in SLOTS}
    for m in meals:
        if req.issubset(set(m.get("tags", []))) and m.get("type") in out:
            out[m["type"]] += 1
    return out


def fmt_row(label, c, lo):
    cells = []
    for s in SLOTS:
        n = c[s]
        mark = "  " if n >= lo else ("!!" if n == 0 else " *")   # * thin, !! empty
        cells.append(f"{n:>3}{mark}")
    total = sum(c.values())
    flag = "" if all(c[s] >= lo for s in SLOTS) else "   <-- THIN"
    return f"  {label:<42}{''.join(cells)}  tot {total:>3}{flag}"


def main():
    lo = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    meals = json.load(open("meals.json"))
    hdr = "  " + " " * 42 + "".join(f"{s[:3].upper():>5}" for s in SLOTS)

    print(f"\nCoverage in meals.json — {len(meals)} meals total")
    print(f"Target: >= {lo} per slot (a full 7-day plan with no repeats). "
          f"* = thin, !! = empty\n")

    print("SINGLE RESTRICTIONS"); print(hdr)
    for r in RESTRICTIONS:
        print(fmt_row(r, counts_by_slot(meals, [r]), lo))

    print("\nHARD COMBOS"); print(hdr)
    thin = []
    for combo in HARD_COMBOS:
        c = counts_by_slot(meals, combo)
        print(fmt_row(" + ".join(combo), c, lo))
        if any(c[s] < lo for s in SLOTS):
            thin.append((combo, c))

    # also scan every restriction PAIR so nothing hides
    print("\nALL RESTRICTION PAIRS BELOW TARGET"); print(hdr)
    any_pair = False
    for combo in combinations(RESTRICTIONS, 2):
        c = counts_by_slot(meals, combo)
        if any(c[s] < lo for s in SLOTS):
            print(fmt_row(" + ".join(combo), c, lo)); any_pair = True
    if not any_pair:
        print("  (all pairs meet the target)")

    print(f"\nSummary: {len(thin)} of {len(HARD_COMBOS)} curated hard combos are thin "
          f"in at least one slot.")
    if thin:
        print("Target more generation for:")
        for combo, c in thin:
            short = ", ".join(f"{s[:1]}:{c[s]}" for s in SLOTS)
            print(f"  - {' + '.join(combo):<40} ({short})")


if __name__ == "__main__":
    main()
