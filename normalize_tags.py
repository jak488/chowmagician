"""Enforce logical tag implications in meals.json (deterministic — no API needed).

Run:  python3 normalize_tags.py
The LLM sometimes tags a meal 'vegan' but forgets that vegan logically implies
'vegetarian' and 'dairy_free'. This normalizes those so dietary filters are
consistent, and zeroes cholesterol on vegan meals. Safe to run repeatedly.
"""
import json

# tag -> tags it logically implies
IMPLIES = {
    "vegan": ["vegetarian", "dairy_free"],
}


def normalize(meals):
    changed = 0
    for m in meals:
        tags = set(m.get("tags", []))
        before = set(tags)
        for t, implied in IMPLIES.items():
            if t in tags:
                tags.update(implied)
        if "vegan" in tags and m.get("cholesterol_mg"):
            m["cholesterol_mg"] = 0
        if tags != before:
            # preserve order: original tags first, then any newly added
            m["tags"] = m.get("tags", []) + [t for t in tags if t not in m.get("tags", [])]
            changed += 1
    return changed


if __name__ == "__main__":
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    meals = json.load(open("meals.json"))
    n = normalize(meals)
    json.dump(meals, open("meals.json", "w"), indent=1)
    print(f"normalized {n} meals (enforced vegan -> vegetarian + dairy_free, cholesterol 0)")
