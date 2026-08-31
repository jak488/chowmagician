"""Background populator: Claude generates tagged meals into meals.json.

Run:  python3 populate_meals.py [target_total]     (default 200)
Generates in batches until meals.json holds target_total meals, de-duplicating by
name and telling Claude which names already exist so each batch stays fresh. Writes
after every batch, so progress is saved even if interrupted.

Needs ANTHROPIC_API_KEY (env var or a .env file next to this script).
Model: set MEAL_MODEL to choose the model (default claude-opus-4-8). For a big, cheap
batch:  MEAL_MODEL=claude-haiku-4-5 python3 populate_meals.py 200
"""
import json, os, sys
from collections import Counter

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
- IMPORTANT for hard combos: include at least 2-3 meals that are simultaneously gluten_free + dairy_free \
+ kidney_healthy for EACH of breakfast, lunch, and dinner, some of them hearty 700+ kcal (lean protein + \
white rice + low-potassium veggies like green beans, cabbage, bell peppers, cauliflower; eggs/egg whites \
are dairy-free, so tag egg dishes without cheese/milk as dairy_free).
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


def generate(n, avoid_names=()):
    import anthropic
    client = anthropic.Anthropic()
    avoid = ""
    if avoid_names:
        avoid = "\n- Do NOT reuse any of these existing meal names (invent different dishes): " + \
                ", ".join(sorted(avoid_names))
    resp = client.messages.create(
        model=os.environ.get("MEAL_MODEL", "claude-opus-4-8"),
        max_tokens=12000,
        system="You are a chef and nutrition-aware meal-planning assistant. Return only data matching the schema.",
        messages=[{"role": "user", "content": PROMPT.format(n=n, avoid=avoid)}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)["meals"]


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    _load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY (env var or a .env file next to this script) first.")
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    BATCH = 20

    existing = json.load(open("meals.json")) if os.path.exists("meals.json") else []
    seen = {m["name"].lower() for m in existing}
    model = os.environ.get("MEAL_MODEL", "claude-opus-4-8")
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
