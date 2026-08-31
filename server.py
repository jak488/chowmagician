"""Local server for the meal-plan mockup: serves index.html + POST /api/mealplan.

The LLM only runs in the background (populate_meals.py). This server just reads
meals.json, filters by the user's dietary restrictions, and assembles a 7-day plan.

Run:  python3 server.py    (http://127.0.0.1:8888)
"""
import http.server, json, os, random, re
from urllib.parse import urlparse, parse_qs

MEALS_FILE = "meals.json"
SHARES = {"breakfast": 0.30, "lunch": 0.35, "dinner": 0.35}


def load_meals():
    try:
        return json.load(open(MEALS_FILE))
    except Exception:
        return []


def _macro_vec(m):
    """Fraction of a meal's calories from (protein, carbs, fat); best-effort if carbs/fat absent."""
    cal = max(m.get("calories", 1), 1)
    p = m.get("protein_g", 0) * 4
    c, f = m.get("carbs_g"), m.get("fat_g")
    if c is not None and f is not None:
        pc, cc, fc = p, c * 4, f * 9
    else:                                   # no carb/fat data yet: split leftover calories evenly
        rem = max(cal - p, 0)
        pc, cc, fc = p, rem * 0.5, rem * 0.5
    tot = pc + cc + fc or 1
    return (pc / tot, cc / tot, fc / tot)


def _complexity(m):
    """Rough recipe-complexity score: number of steps (sentences) + a bit for ingredient count."""
    steps = len(re.findall(r"[.!?](?:\s|$)", m.get("instructions", ""))) or 1
    return steps + 0.25 * len(m.get("ingredients", []))


def build_plan(calories, protein, restrictions, macros=None, complexity=None):
    meals = load_meals()
    filt = [m for m in meals if all(r in m.get("tags", []) for r in restrictions)]
    by_type = {t: [m for m in filt if m.get("type") == t] for t in SHARES}

    days, last = [], {}
    for d in range(7):
        day = {"day": d + 1, "meals": {},
               "totals": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}}
        for slot in ("breakfast", "lunch", "dinner"):
            pool = by_type[slot]
            if not pool:
                day["meals"][slot] = None
                continue
            target = calories * SHARES[slot]
            if macros:                           # match the full protein/carb/fat calorie split
                ranked = sorted(pool, key=lambda m: sum(
                    abs(a - b) for a, b in zip(_macro_vec(m), macros)))
            elif protein:                        # match protein density to the requested ratio
                dens = protein / max(calories, 1)
                ranked = sorted(pool, key=lambda m: abs(
                    m.get("protein_g", 0) / max(m.get("calories", 1), 1) - dens))
            else:                                # no target -> just pick closest by calories
                ranked = sorted(pool, key=lambda m: abs(m.get("calories", 0) - target))
            if complexity == "simple":           # bias toward simpler recipes among good matches
                ranked = sorted(ranked[:8], key=_complexity)
            elif complexity == "involved":       # bias toward more involved recipes
                ranked = sorted(ranked[:8], key=_complexity, reverse=True)
            top = ranked[:4]
            top = [m for m in top if m.get("id") != last.get(slot)] or top   # avoid same meal 2 days running
            pick = random.choice(top)
            last[slot] = pick.get("id")
            # scale the portion so the meal fills its slot's share of the calorie target
            portion = min(3.0, max(0.5, round((target / max(pick.get("calories", 1), 1)) * 20) / 20))
            m = dict(pick)
            m["portion"] = portion
            for f in ("calories", "protein_g", "carbs_g", "fat_g",
                      "sodium_mg", "potassium_mg", "cholesterol_mg"):
                if f in m:
                    m[f] = round(pick[f] * portion)
            day["meals"][slot] = m
            day["totals"]["calories"] += m["calories"]
            day["totals"]["protein"] += m["protein_g"]
            day["totals"]["carbs"] += m.get("carbs_g") or 0
            day["totals"]["fat"] += m.get("fat_g") or 0
        days.append(day)

    return {"days": days, "filtered_count": len(filt),
            "target": {"calories": calories, "protein": protein, "macros": macros}}


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/meal":                                  # single meal by id
            qs = parse_qs(urlparse(self.path).query)
            try:
                mid = int(qs.get("id", [""])[0])
            except ValueError:
                mid = None
            meal = next((m for m in load_meals() if m.get("id") == mid), None)
            out = json.dumps(meal or {"error": "not found"}).encode()
            self.send_response(200 if meal else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return
        if path == "/meal" or path.startswith("/meal/"):         # client-side route -> serve the app
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] != "/api/mealplan":
            self.send_error(404)
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            raw = body.get("macros")
            macros = None
            if isinstance(raw, dict):
                p, c, f = (float(raw.get("protein", 0)), float(raw.get("carbs", 0)),
                           float(raw.get("fat", 0)))
                s = p + c + f
                if s > 0:
                    macros = (p / s, c / s, f / s)
            plan = build_plan(int(body.get("calories") or 2000),
                              int(body.get("protein") or 0),
                              body.get("restrictions", []),
                              macros,
                              body.get("complexity") or None)
            out = json.dumps(plan).encode(); status = 200
        except Exception as e:
            out = json.dumps({"error": str(e)}).encode(); status = 500
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    port = int(os.environ.get("PORT", 8888))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    print("MealPlan mockup on http://127.0.0.1:%d  (%d meals in datastore)" % (port, len(load_meals())))
    httpd.serve_forever()
