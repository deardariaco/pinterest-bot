"""
DearDariaCo Pinterest auto-poster (v2 - full catalog).

Works from content_bank_v2.json, which has every listing (jackets, sleeves,
menus, place cards, RSVPs, save the dates, glass tags, bundles) grouped by
suite - not just bundles.

An item only becomes eligible to post once both its `listing_url` and
`images` fields are filled in. Everything else is skipped automatically.

Environment variables:
  PINTEREST_ACCESS_TOKEN, IMAGE_BASE_URL, DRY_RUN, PINS_PER_RUN
"""

import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_DIR = Path(__file__).parent
CONTENT_BANK_PATH = BASE_DIR / "content_bank_v2.json"
LOG_PATH = BASE_DIR / "posted_log.json"

PINTEREST_API_BASE = "https://api.pinterest.com/v5"

PINS_PER_RUN = int(os.environ.get("PINS_PER_RUN", "10"))
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"
ACCESS_TOKEN = os.environ.get("PINTEREST_ACCESS_TOKEN", "")
IMAGE_BASE_URL = os.environ.get("IMAGE_BASE_URL", "").rstrip("/")

BANNED_PHRASES = ["hand-drawn", "—"]  # house rules: no em dashes, no "hand-drawn"

PRODUCT_TYPE_PHRASES = {
    "bundle": "a full matching wedding stationery suite",
    "sleeve": "an invitation sleeve",
    "place_card": "a place card",
    "rsvp": "an RSVP card",
    "save_the_date": "a save the date card",
    "menu": "a menu card",
    "glass_tag": "a wine glass tag",
    "other": "a wedding stationery piece",
}

DESCRIPTION_TEMPLATES = [
    "This {theme_word} {suite_name} design is {product_phrase}, made for Cricut Print Then Cut. Just download, print, and cut at home.",
    "A {theme_word} {suite_name} piece for your wedding stationery lineup. This is {product_phrase}, ready for Cricut Print Then Cut.",
    "Planning a {theme_word} wedding? This {suite_name} piece is {product_phrase} for Cricut Print Then Cut, easy to customize at home.",
    "Say hello to your new favorite {suite_name} design. {theme_word_cap} details throughout, built for Cricut Print Then Cut.",
    "This {suite_name} piece brings {theme_word} style to your wedding stationery. Made for Cricut Print Then Cut and easy to personalize.",
]


def load_json(path, default):
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def clean_text(text):
    for phrase in BANNED_PHRASES:
        if phrase in text:
            raise ValueError(f"Generated text contains banned phrase '{phrase}': {text}")
    return text


def build_pin_pool(content_bank, log):
    recent_cutoff = 7
    recent_keys = set()
    now = datetime.now(timezone.utc)
    for entry in log.get("history", []):
        posted_at = datetime.fromisoformat(entry["posted_at"])
        if (now - posted_at).days < recent_cutoff:
            recent_keys.add((entry["suite_id"], entry["title"]))

    pool = []
    for suite_id, suite in content_bank["suites"].items():
        for item in suite["items"]:
            if item["listing_url"].startswith("PASTE_") or not item.get("images"):
                continue
            if (suite_id, item["title"]) in recent_keys:
                continue
            pool.append((suite_id, suite, item))
    return pool


def generate_copy(suite, item, log):
    theme_word = random.choice(suite["theme_words"])
    product_phrase = PRODUCT_TYPE_PHRASES.get(item["product_type"], PRODUCT_TYPE_PHRASES["other"])

    desc_idx = log.get("next_desc_template_idx", 0) % len(DESCRIPTION_TEMPLATES)
    description = DESCRIPTION_TEMPLATES[desc_idx].format(
        suite_name=suite["display_name"],
        theme_word=theme_word,
        theme_word_cap=theme_word.capitalize(),
        product_phrase=product_phrase,
    )
    log["next_desc_template_idx"] = desc_idx + 1

    hashtags = item["hashtags"][:10]
    random.shuffle(hashtags)
    hashtag_line = " ".join(hashtags)
    full_description = clean_text(f"{description}\n\n{hashtag_line}")

    title = clean_text(item["title"][:100])
    return title, full_description


def post_pin(suite, item):
    chosen_image = random.choice(item["images"])
    image_url = f"{IMAGE_BASE_URL}/{chosen_image}"
    title, description = generate_copy(suite, item, log_ref[0])

    payload = {
        "board_id": suite.get("board_id", suite["board"]),
        "title": title,
        "description": description,
        "link": item["listing_url"],
        "media_source": {"source_type": "image_url", "url": image_url},
    }

    if DRY_RUN or not ACCESS_TOKEN:
        print("---- DRY RUN (no pin actually posted) ----")
        print(json.dumps(payload, indent=2))
        return {"dry_run": True}, title

    resp = requests.post(
        f"{PINTEREST_API_BASE}/pins",
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json(), title


log_ref = [None]  # small trick so post_pin can reach the log without a global rewrite


def main():
    content_bank = load_json(CONTENT_BANK_PATH, {"suites": {}})
    log = load_json(LOG_PATH, {"history": [], "next_desc_template_idx": 0})
    log_ref[0] = log

    pool = build_pin_pool(content_bank, log)
    if not pool:
        print("No eligible items to post. Make sure listing_url and images are filled in for at least a few items.")
        return

    random.shuffle(pool)
    todays_pins = pool[:PINS_PER_RUN]

    for suite_id, suite, item in todays_pins:
        result, title = post_pin(suite, item)

        log.setdefault("history", []).append({
            "suite_id": suite_id,
            "title": title,
            "posted_at": datetime.now(timezone.utc).isoformat(),
            "result": "dry_run" if result.get("dry_run") else result.get("id", "unknown"),
        })
        save_json(LOG_PATH, log)

        print(f"Posted: {suite['display_name']} / {item['product_type']} / {title}")
        time.sleep(2)


if __name__ == "__main__":
    main()
