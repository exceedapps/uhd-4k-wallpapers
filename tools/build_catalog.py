#!/usr/bin/env python3
"""Build the wallpaper catalog: efficient WebP derivatives + manifest.json.

Scans content/catalog/<category>/*.png (whatever files actually exist — deletions are
respected automatically) and, for each source PNG, produces:
  • thumb   -> catalog/<cat>/thumbs/<name>.webp    (~480px wide, q80)  — the grid
  • regular -> catalog/<cat>/preview/<name>.webp   (<=1440px, q95)     — detail preview.
              q95 is visually lossless (no dark banding — that was a q88 artifact) yet
              5-40x smaller than the PNG, so the detail pager loads fast.
  • full    -> catalog/<cat>/<name>.png            (untouched original) — HQ (rewarded)

Then writes:
  • content/manifest.json                    (served locally / pushed to the CDN)
  • app/src/main/assets/manifest.json        (bundled fallback so the app never blanks)

The Home "All" feed is round-robin interleaved across categories so it looks varied and
premium instead of 30 of one category in a row. Re-runnable & incremental (skips WebP
derivatives that are already up to date).

Usage:  python3 tools/build_catalog.py
"""
import json, os, re, sys, random
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "content", "catalog")
MANIFEST = os.path.join(ROOT, "content", "manifest.json")
ASSETS_MANIFEST = os.path.join(ROOT, "app", "src", "main", "assets", "manifest.json")

THUMB_W, THUMB_Q = 480, 80
# Detail preview: WebP q95 at up to 1440px. q95 is visually lossless (the earlier banding on
# dark gradients was purely a LOW-quality q88 artifact) but 5–40× smaller than the PNG, so
# the detail pager loads fast. Written to a NEW `preview/` folder so on-device caches that
# still hold the old q88 `regular/` webp are naturally bypassed.
PREVIEW_W, PREVIEW_Q = 1440, 95

# Pretty display names + a premium one-word title per category.
CATS = {
    "nature_landscape": ("Nature",        "Wilderness"),
    "dark_nature":      ("Dark Nature",   "Nightfall"),
    "mountains_peaks":  ("Mountains",     "Summit"),
    "ocean_water":      ("Ocean",         "Tides"),
    "beach_tropical":   ("Beach",         "Paradise"),
    "forest_woods":     ("Forest",        "Wildwood"),
    "sunset_sky":       ("Sunset",        "Afterglow"),
    "aurora_lights":    ("Aurora",        "Northern Lights"),
    "city_skyline":     ("City",          "Metropolis"),
    "space_galaxy":     ("Space",         "Cosmos"),
    "black_hole":       ("Black Hole",    "Event Horizon"),
    "abstract_gradient":("Abstract",      "Flow"),
    "lux_abstract":     ("Lux Abstract",  "Liquid Luxe"),
    "amoled_dark":      ("AMOLED",        "Pure Black"),
    "minimal_clean":    ("Minimal",       "Less"),
    "neon_glow":        ("Neon",          "Nightglow"),
    "floral_macro":     ("Floral",        "Bloom"),
    "locked_in":        ("Locked In",     "Discipline"),
    "devoted":          ("Devoted",       "Faith"),
    "old_money":        ("Old Money",     "Quiet Luxury"),
    "dark_aesthetic":   ("Aesthetic",     "After Dark"),
    "animals":          ("Animals",       "Apex"),
    "cars":             ("Cars",          "Drive"),
    "memes":            ("Memes",         "Mood"),
    "monochrome":       ("Monochrome",    "Black & White"),
}
# Order categories are presented in (nicer than alphabetical); unknown ones appended.
ORDER = ["old_money", "dark_aesthetic", "monochrome", "cars", "animals", "memes", "lux_abstract", "city_skyline", "locked_in",
         "devoted", "nature_landscape", "dark_nature", "abstract_gradient",
         "ocean_water", "beach_tropical", "black_hole"]


# Category folders kept out of the published catalog (awaiting a decision).
# "Cars" (capital C) was the holding folder; published cars live in "cars". Images with a brand
# name written large in the picture stay out (content/catalog_hold/).
HOLD = {"Cars", "new", "New"}  # "new"/"New" at catalog root = unsorted uploads, never a category


def convert(src, dst, width, quality):
    """Write a WebP derivative (never upscaling); skip if already newer than src."""
    if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return
    with Image.open(src) as im:
        im = im.convert("RGB")
        if im.width > width:
            h = round(im.height * width / im.width)
            im = im.resize((width, h), Image.LANCZOS)
        im.save(dst, "WEBP", quality=quality, method=6)


def build():
    if not os.path.isdir(CATALOG):
        print("no catalog dir"); sys.exit(1)

    present = [d for d in os.listdir(CATALOG)
               if os.path.isdir(os.path.join(CATALOG, d)) and d not in HOLD]
    cats_sorted = [c for c in ORDER if c in present] + sorted(c for c in present if c not in ORDER)

    per_cat = {}        # cat -> list of wallpaper dicts
    categories = []
    total_src = 0

    for cat in cats_sorted:
        cdir = os.path.join(CATALOG, cat)
        pngs = sorted(f for f in os.listdir(cdir) if f.lower().endswith(".png"))
        if not pngs:
            continue
        name, title = CATS.get(cat, (cat.replace("_", " ").title(), "Wallpaper"))
        os.makedirs(os.path.join(cdir, "thumbs"), exist_ok=True)
        os.makedirs(os.path.join(cdir, "preview"), exist_ok=True)
        items = []
        for f in pngs:
            stem = os.path.splitext(f)[0]
            src = os.path.join(cdir, f)
            try:
                convert(src, os.path.join(cdir, "thumbs", stem + ".webp"), THUMB_W, THUMB_Q)
                # Detail preview: fast, visually-lossless q95 WebP (see PREVIEW_* above).
                convert(src, os.path.join(cdir, "preview", stem + ".webp"), PREVIEW_W, PREVIEW_Q)
            except Exception as e:
                print(f"  ! skip {cat}/{f}: {e}")
                continue
            items.append({
                "id": stem,
                "title": title,
                "category": cat,
                "author": "AI",
                "thumb": f"catalog/{cat}/thumbs/{stem}.webp",
                "regular": f"catalog/{cat}/preview/{stem}.webp",
                "full": f"catalog/{cat}/{f}",
            })
        if items:
            # NEW images (named "<cat>_new_NN") are surfaced FIRST, in numeric order, so the
            # freshest/highest-quality wallpapers lead each category (and the Home feed). The
            # rest are seeded-shuffled so the older dark (_NN), vibrant (_wNN) and Gallerie
            # (_cNN) sets stay mixed (deterministic across rebuilds → favorites/pager stable).
            # Newest batch first ("_new_b3_" before "_new_b2_"), numeric order inside a batch.
            def new_key(i):
                m = re.search(r"_new_b(\d+)_(\d+)$", i["id"])
                return (-int(m.group(1)), int(m.group(2))) if m else (0, 0)
            new_items = sorted((i for i in items if "_new_" in i["id"]), key=new_key)
            old_items = [i for i in items if "_new_" not in i["id"]]
            random.Random(cat).shuffle(old_items)
            items = new_items + old_items
            per_cat[cat] = items
            categories.append({"id": cat, "name": name})
            total_src += len(items)
            print(f"{name:14} {len(items):3} wallpapers")

    # Round-robin interleave across categories for a varied "All" feed.
    feed, i = [], 0
    lists = [per_cat[c["id"]] for c in categories]
    while any(i < len(l) for l in lists):
        for l in lists:
            if i < len(l):
                feed.append(l[i])
        i += 1

    manifest = {"version": 2, "categories": categories, "wallpapers": feed}
    with open(MANIFEST, "w") as fp:
        json.dump(manifest, fp, indent=2)
    os.makedirs(os.path.dirname(ASSETS_MANIFEST), exist_ok=True)
    with open(ASSETS_MANIFEST, "w") as fp:
        json.dump(manifest, fp, indent=2)

    print(f"\nTOTAL: {total_src} wallpapers, {len(categories)} categories")
    print(f"manifest -> {MANIFEST}")
    print(f"bundled  -> {ASSETS_MANIFEST}")


if __name__ == "__main__":
    build()
