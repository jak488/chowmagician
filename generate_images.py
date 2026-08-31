"""Generate a food photo for each recipe in meals.json using OpenAI's image API.

Run:  python3 generate_images.py [limit]
Reads meals.json, and for every meal without an image yet, asks OpenAI to generate a
photo, saves it to images/<slug>.jpg, and writes "image": "images/<slug>.jpg" back
into the meal. Resumable: skips meals whose image file already exists. Saves
meals.json after each image, so progress is never lost.

Needs OPENAI_API_KEY (env var or a .env file next to this script).
Config via env vars:
  OPENAI_IMAGE_MODEL  default gpt-image-1  (use dall-e-3 if gpt-image-1 isn't verified)
  IMAGE_SIZE          default 1024x1024
  IMAGE_QUALITY       default medium       (low|medium|high for gpt-image-1)
Cost: gpt-image-1 at 1024x1024 is ~$0.01 (low) / ~$0.04 (medium) / ~$0.17 (high) per image.
"""
import base64, json, os, re, sys, urllib.request, urllib.error

API_URL = "https://api.openai.com/v1/images/generations"
MEALS_FILE = "meals.json"
IMG_DIR = "images"


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


def slugify(name, mid):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{s}-{mid}"


def build_prompt(meal):
    ingredients = "; ".join(meal.get("ingredients", []))
    steps = " ".join(meal.get("instructions", "").split())
    return (f"A bright, minimal, mouth-wateringly appetizing food photograph of the finished, plated dish "
            f"\"{meal['name']}\". It contains: {ingredients}. "
            f"Use this preparation only to depict how the completed dish looks — form, texture, color, "
            f"garnish, and serving vessel: {steps} "
            f"Style it like high-end editorial food photography: fresh, vibrant ingredients and enticing "
            f"textures — glistening sauces, crisp golden edges, a good sear on meats, tender juicy proteins, "
            f"flaky fish, melty cheese, fluffy grains, gentle steam rising from hot dishes — with a light "
            f"scattering of fresh herbs or garnish where fitting, and natural moisture and sheen so it looks "
            f"freshly made and irresistible. Soft, even natural window light with gentle highlights, shallow "
            f"depth of field with the food in crisp sharp focus, a slight overhead angle, plated on simple "
            f"clean tableware over a bright, light background with plenty of negative space and minimal, "
            f"tasteful props. Show the dish exactly as it would be served. No text, no watermark, no clutter.")


def generate_image(prompt, path, key, model, size, quality):
    body = {"model": model, "prompt": prompt, "n": 1, "size": size, "quality": quality}
    req = urllib.request.Request(API_URL, data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        item = json.load(r)["data"][0]
    # gpt-image-1 returns base64; dall-e models may return a url instead
    if item.get("b64_json"):
        data = base64.b64decode(item["b64_json"])
    else:
        with urllib.request.urlopen(item["url"], timeout=180) as r:
            data = r.read()
    with open(path, "wb") as f:
        f.write(data)


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    _load_dotenv()
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("Set OPENAI_API_KEY (env var or a .env file next to this script) first.")
    model = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")
    size = os.environ.get("IMAGE_SIZE", "1024x1024")
    quality = os.environ.get("IMAGE_QUALITY", "medium")
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10**9
    os.makedirs(IMG_DIR, exist_ok=True)

    meals = json.load(open(MEALS_FILE))
    todo = [m for m in meals if not (m.get("image") and os.path.exists(m["image"]))]
    print(f"{len(meals)} meals · {len(meals) - len(todo)} already have images · "
          f"generating up to {min(limit, len(todo))} with {model} ({size}, {quality})")

    done = 0
    for m in todo:
        if done >= limit:
            break
        path = os.path.join(IMG_DIR, slugify(m["name"], m["id"]) + ".jpg")
        try:
            generate_image(build_prompt(m), path, key, model, size, quality)
        except urllib.error.HTTPError as e:
            print(f"  ! {m['name']}: HTTP {e.code} {e.read()[:300]!r}"); break
        except Exception as e:
            print(f"  ! {m['name']}: {e}"); continue
        m["image"] = path
        json.dump(meals, open(MEALS_FILE, "w"), indent=1)   # save after each image
        done += 1
        print(f"  [{done}] {m['name']}  ->  {path}")

    print(f"done: {done} images generated; "
          f"{sum(1 for m in meals if m.get('image'))}/{len(meals)} meals now have images")


if __name__ == "__main__":
    main()
