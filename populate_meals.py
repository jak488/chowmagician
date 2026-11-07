"""Background populator: Claude generates tagged meals into meals.json.

Run:  python3 populate_meals.py [target_total]     (default 200)
Generates in batches until meals.json holds target_total meals, de-duplicating by
name and telling Claude which names already exist so each batch stays fresh. Writes
after every batch, so progress is saved even if interrupted.

Targeted top-up for a thin restriction combo (see coverage_check.py):
  python3 populate_meals.py --combo vegan,kidney_healthy 24
generates ~24 NEW meals that all satisfy every listed tag, appended to meals.json.

Needs ANTHROPIC_API_KEY (env var or a .env file next to this script).
Model: set MEAL_MODEL to choose the model (default claude-opus-4-8). For a big, cheap
batch:  MEAL_MODEL=claude-haiku-4-5 python3 populate_meals.py 200
"""
import json, os, sys
from collections import Counter
from normalize_tags import normalize   # enforce vegan -> vegetarian + dairy_free after generating

TAGS = ["vegetarian", "vegan", "gluten_free", "dairy_free",
        "heart_healthy", "kidney_healthy", "high_protein", "keto"]

SCHEMA = {
    "type": "object",
    "properties": {
        "meals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": ["breakfast", "lunch", "dinner", "snack"]},
                    "calories": {"type": "integer"},
                    "protein_g": {"type": "integer"},
                    "carbs_g": {"type": "integer"},
                    "fat_g": {"type": "integer"},
                    "sodium_mg": {"type": "integer"},
                    "potassium_mg": {"type": "integer"},
                    "cholesterol_mg": {"type": "integer"},
                    "tags": {"type": "array", "items": {"type": "string", "enum": TAGS}},
                    "ingredients": {"type": "array", "items": {"type": "string"}},
                    "instructions": {"type": "string"},
                },
                "required": ["name", "type", "calories", "protein_g", "carbs_g", "fat_g",
                             "sodium_mg", "potassium_mg", "cholesterol_mg", "tags",
                             "ingredients", "instructions"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["meals"],
    "additionalProperties": False,
}

PROMPT = """Generate {n} diverse, realistic, home-cookable single-serving meals for a meal-planning app.

Rules:
- Spread them across breakfast, lunch, and dinner (a good mix), plus some snacks.
- Vary calories WIDELY. Include MANY hearty, higher-calorie meals in the 700-1000 kcal range (pasta and \
rice dishes, burritos, curries and stews with generous portions, loaded grain bowls, big breakfasts, \
burgers) alongside lighter 250-500 kcal options. Do NOT cluster everything around 400-500.
- Vary the MACRONUTRIENT mix widely too, not just calories. Deliberately include both extremes: some \
LOW-FAT meals (under ~10g fat — lean poultry, white fish, egg whites, grain-and-veg bowls) AND some \
HIGH-FAT meals (avocado, nuts, cheese, oils, fatty fish); some LOW-CARB meals AND some HIGH-CARB meals \
(pasta, rice, potatoes, oats, fruit); and protein ranging from modest to very high. Do NOT cluster every \
meal around a balanced ~30/40/30 protein/carb/fat split — spread them across the whole spectrum.
- Ensure good coverage of these diets, with SEVERAL qualifying meals for each: vegetarian, vegan, \
gluten_free, dairy_free, heart_healthy, kidney_healthy, high_protein.
- CRITICAL — hard restrictive combos need deliberate OVER-representation, because they are naturally \
rare and a 7-day plan needs 7 of each meal type. Treat these as explicit quotas to hit across the full \
run (spread the effort over batches), for EACH of breakfast, lunch, and dinner:
    * gluten_free + kidney_healthy: aim for >=8 per meal type
    * gluten_free + dairy_free + kidney_healthy: aim for >=8 per meal type
    * dairy_free + kidney_healthy: >=8 per meal type
    * heart_healthy + kidney_healthy: >=8 per meal type
    * vegan + kidney_healthy: >=5 per meal type (hard — lean on tofu, egg-white is NOT vegan; use \
low-potassium plant foods: white rice, cauliflower, green beans, bell peppers, cabbage; avoid beans, \
nuts, potatoes, tomatoes, spinach, bananas)
    * vegan + gluten_free and vegetarian + gluten_free + dairy_free: >=6 per meal type
  Build these from lean protein + white rice/low-potassium veggies; make some hearty 700+ kcal. Eggs/egg \
whites are dairy-free (tag egg dishes without cheese/milk as dairy_free) but are NOT vegan.
- Tag each meal with ALL applicable tags. Be consistent: a vegan meal is also vegetarian and dairy_free; \
a meal with >=30g protein is high_protein; kidney_healthy means lower sodium/potassium/phosphorus \
(avoid heavy beans, dairy, nuts, potatoes, tomatoes, bananas for those); keto means very low carb \
(roughly <15g carbs per serving), higher fat, moderate protein — avoid grains, bread, pasta, rice, \
potatoes, sugar, most fruit, and legumes; a keto meal is usually also gluten_free. Include SEVERAL keto \
meals across breakfast, lunch, and dinner.
- calories, protein_g, carbs_g, fat_g, sodium_mg, potassium_mg, and cholesterol_mg are rough per-serving \
estimates (integers; grams for macros, mg for the minerals). cholesterol_mg is 0 for any vegan meal. \
kidney_healthy meals should have lower potassium and sodium; heart_healthy meals lower cholesterol and \
sodium; keto meals should have low carbs_g and higher fat_g.
- ingredients: a full list with rough quantities, and INCLUDE the seasonings, spices, herbs, and \
aromatics that make the dish flavorful. Name specific ones (e.g. smoked paprika, cumin, coriander, fresh \
thyme, garlic, ginger, lemon zest, chili flakes, soy sauce, miso) rather than a generic "seasoning". Not \
every dish needs heavy spicing, but many should be genuinely well-seasoned and reflect their cuisine.
- For heart_healthy and kidney_healthy meals, build flavor with herbs, spices, citrus, vinegar, and \
aromatics INSTEAD of salt (keep sodium low).
- instructions: clear, detailed steps someone could actually cook from — prep, cook (with rough \
temperatures/times), when to add the seasonings, and how to finish/serve. Use as many steps as the recipe \
GENUINELY needs, matched to its complexity: roughly 2-3 for very simple dishes (a smoothie, overnight oats, \
a snack plate) and up to 7-8 for involved ones (a curry, a layered bake, a braise). Do NOT force a fixed \
number of steps — let it vary naturally. Write each step as a full sentence.
- Use varied cuisines and proteins; keep names distinct.{avoid}"""


def _load_dotenv(path=".env"):
    try:
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and v and k not in os.environ:
                    os.environ[k] = v
    except FileNotFoundError:
        pass


COMBO_PROMPT = """Generate {n} diverse, realistic, home-cookable single-serving meals that EVERY ONE of \
them satisfies ALL of these dietary tags simultaneously: {tags}.

Rules:
- EVERY meal must genuinely qualify for ALL of those tags at once — this is the whole point. Tag each \
meal with those tags plus any others that also apply.
- Spread them roughly evenly across breakfast, lunch, and dinner (and a few snacks if natural).
- Vary calories and the protein/carb/fat mix; include some hearty 700+ kcal options.
- Reminders: vegan = no animal products at all (no eggs, dairy, meat, fish, honey); eggs/egg whites are \
dairy_free and vegetarian but NOT vegan; kidney_healthy = low sodium, potassium, and phosphorus — avoid \
beans, lentils, nuts, potatoes, tomatoes, spinach, bananas, dairy, whole grains; lean on white rice, \
cauliflower, green beans, cabbage, bell peppers, and (for vegan+kidney) tofu and low-potassium plant \
foods; heart_healthy = low cholesterol and sodium, unsaturated fats; build flavor with herbs, spices, \
citrus, and aromatics instead of salt.
- carbs_g, fat_g, sodium_mg, potassium_mg, cholesterol_mg are rough per-serving integer estimates; \
cholesterol_mg is 0 for vegan meals.
- ingredients: a full list with rough quantities including specific seasonings/spices. instructions: \
clear, detailed steps as full sentences, as many as the recipe genuinely needs.
- Use varied cuisines and proteins; keep names distinct.{avoid}"""


def _call(prompt_text):
    import anthropic
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=os.environ.get("MEAL_MODEL", "claude-opus-4-8"),
        max_tokens=12000,
        system="You are a chef and nutrition-aware meal-planning assistant. Return only data matching the schema.",
        messages=[{"role": "user", "content": prompt_text}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)["meals"]


def _avoid_str(avoid_names):
    if not avoid_names:
        return ""
    return "\n- Do NOT reuse any of these existing meal names (invent different dishes): " + \
           ", ".join(sorted(avoid_names))


def generate(n, avoid_names=()):
    return _call(PROMPT.format(n=n, avoid=_avoid_str(avoid_names)))


def generate_combo(n, tags, avoid_names=()):
    return _call(COMBO_PROMPT.format(n=n, tags=" + ".join(tags), avoid=_avoid_str(avoid_names)))


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    _load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY (env var or a .env file next to this script) first.")
    model = os.environ.get("MEAL_MODEL", "claude-opus-4-8")
    BATCH = 20

    # targeted mode:  python3 populate_meals.py --combo vegan,kidney_healthy [count]
    combo = None
    if len(sys.argv) > 1 and sys.argv[1] == "--combo":
        combo = [t.strip() for t in sys.argv[2].split(",") if t.strip()]
        want = int(sys.argv[3]) if len(sys.argv) > 3 else 24       # new meals to ADD for this combo
    else:
        target = int(sys.argv[1]) if len(sys.argv) > 1 else 200    # total meals to reach

    existing = json.load(open("meals.json")) if os.path.exists("meals.json") else []
    seen = {m["name"].lower() for m in existing}

    if combo:   # ── targeted top-up for one hard combo ───────────────────────────
        print(f"targeting combo [{' + '.join(combo)}] · adding up to {want} · model {model}")
        added_total, stalls = 0, 0
        while added_total < want and stalls < 3:
            need = min(BATCH, want - added_total + 4)
            try:
                batch = generate_combo(need, combo, avoid_names=list(seen))
            except Exception as e:
                print("  batch failed:", e); break
            added = 0
            for m in batch:
                if m["name"].lower() in seen:
                    continue
                if not set(combo).issubset(set(m.get("tags", []))):   # enforce the combo
                    continue
                m["id"] = len(existing) + 1
                existing.append(m); seen.add(m["name"].lower())
                added += 1; added_total += 1
                if added_total >= want:
                    break
            normalize(existing)
            json.dump(existing, open("meals.json", "w"), indent=1)
            print(f"  +{added} qualifying  ->  {added_total}/{want} added  ({len(existing)} total)")
            stalls = stalls + 1 if added == 0 else 0
        print(f"\ndone: added {added_total} [{' + '.join(combo)}] meals -> {len(existing)} total")
        return

    print(f"target {target} meals · currently {len(existing)} · model {model}")

    stalls = 0
    while len(existing) < target and stalls < 3:
        need = min(BATCH, target - len(existing) + 5)   # slight over-ask to offset duplicates
        try:
            batch = generate(need, avoid_names=list(seen))
        except Exception as e:
            print("  batch failed:", e); break
        added = 0
        for m in batch:
            if m["name"].lower() in seen:
                continue
            m["id"] = len(existing) + 1
            existing.append(m); seen.add(m["name"].lower()); added += 1
            if len(existing) >= target:
                break
        normalize(existing)                                      # keep tags logically consistent
        json.dump(existing, open("meals.json", "w"), indent=1)   # save after every batch
        print(f"  +{added} new  ->  {len(existing)} total")
        stalls = stalls + 1 if added == 0 else 0

    typ = Counter(m["type"] for m in existing)
    tag = Counter(t for m in existing for t in m.get("tags", []))
    cals = sorted(m["calories"] for m in existing)
    print(f"\ndone: {len(existing)} meals")
    print("  by type:", dict(typ))
    print("  by tag :", dict(tag))
    if cals:
        print(f"  calories: min {cals[0]}, median {cals[len(cals)//2]}, max {cals[-1]}, "
              f">=700kcal: {sum(1 for c in cals if c>=700)}")


if __name__ == "__main__":
    main()
