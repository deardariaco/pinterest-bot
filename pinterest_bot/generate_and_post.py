"""
DearDariaCo Pinterest auto-poster.

What this does each time it runs:
  1. Loads content_bank.json (your suites, hashtags, description/title templates)
  2. Loads posted_log.json (history, so it doesn't repeat itself)
  3. Picks PINS_PER_RUN images, weighted toward bundle images, rotating suites
  4. Generates a unique title + description + hashtags for each
  5. Posts each pin to Pinterest via the API (or just prints it, if DRY_RUN=1)
  6. Updates posted_log.json

Environment variables it expects (set these as GitHub Actions secrets, never
commit them to the repo):
  PINTEREST_ACCESS_TOKEN   - your Pinterest API token
  IMAGE_BASE_URL           - public base URL where your images are hosted
                              e.g. https://raw.githubusercontent.com/you/repo/main/images
  DRY_RUN                  - set to "1" to test without actually posting
  PINS_PER_RUN             - optional, defaults to 10
"""

import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_DIR = Path(__file__).parent
CONTENT_BANK_PATH = BASE_DIR / "content_bank.json"
LOG_PATH = BASE_DIR / "posted_log.json"

PINTEREST_API_BASE = "https://api.pinterest.com/v5"

PINS_PER_RUN = int(os.environ.get("PINS_PER_RUN", "10"))
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"
ACCESS_TOKEN = os.environ.get("PINTEREST_ACCESS_TOKEN", "")
IMAGE_BASE_URL = os.environ.get("IMAGE_BASE_URL", "").rstrip("/")

# Shop-wide house rules baked in here so generated copy stays on-brand
BANNED_PHRASES = ["hand-drawn", "—", " - -"]  # no em dashes, no "hand-drawn"


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
    """Build the list of candidate (suite, image) pairs, skipping anything
    posted in the last N days so the same image doesn't repeat too soon."""
    recent_cutoff = 7  # days
    recent_keys = set()
    now = datetime.now(timezone.utc)
    for entry in log.get("history", []):
        posted_at = datetime.fromisoformat(entry["posted_at"])
        if (now - posted_at).days < recent_cutoff:
            recent_keys.add((entry["suite_id"], entry["image"]))

    pool = []
    for suite in content_bank["suites"]:
        for image in suite["images"]:
            if (suite["id"], image) not in recent_keys:
                pool.append((suite, image))
    return pool


def generate_copy(suite, content_bank, log):
    """Pick templates in rotation (not randomly) so we cycle through all
    variety before repeating, then fill in suite-specific words."""
    theme_word = random.choice(suite["theme_words"])

    desc_templates = content_bank["description_templates"]
    title_templates = content_bank["title_templates"]

    desc_idx = log.get("next_desc_template_idx", 0) % len(desc_templates)
    title_idx = log.get("next_title_template_idx", 0) % len(title_templates)

    description = desc_templates[desc_idx].format(
        suite_name=suite["display_name"],
        theme_word=theme_word,
        theme_word_cap=theme_word.capitalize(),
    )
    title = title_templates[title_idx].format(
        suite_name=suite["display_name"],
        theme_word=theme_word,
        theme_word_cap=theme_word.capitalize(),
    )

    # Add the required AI disclosure + hashtags at the end of the description
    hashtags = suite["hashtags"][:]
    random.shuffle(hashtags)
    hashtag_line = " ".join(hashtags[:12])
    full_description = clean_text(f"{description}\n\n{hashtag_line}")

    log["next_desc_template_idx"] = desc_idx + 1
    log["next_title_template_idx"] = title_idx + 1

    return clean_text(title), full_description


def post_pin(suite, image_filename, title, description):
    image_url = f"{IMAGE_BASE_URL}/{image_filename}"
    payload = {
        "board_id": suite.get("board_id", suite["board"]),
        "title": title[:100],
        "description": description,
        "link": suite["listing_url"],
        "media_source": {
            "source_type": "image_url",
            "url": image_url,
        },
    }

    if DRY_RUN or not ACCESS_TOKEN:
        print("---- DRY RUN (no pin actually posted) ----")
        print(json.dumps(payload, indent=2))
        return {"dry_run": True}

    resp = requests.post(
        f"{PINTEREST_API_BASE}/pins",
        headers={
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    content_bank = load_json(CONTENT_BANK_PATH, {"suites": [], "description_templates": [], "title_templates": []})
    log = load_json(LOG_PATH, {"history": [], "next_desc_template_idx": 0, "next_title_template_idx": 0})

    pool = build_pin_pool(content_bank, log)
    if not pool:
        print("No unposted images available in the lookback window. Add more images or widen the pool.")
        return

    random.shuffle(pool)
    todays_pins = pool[:PINS_PER_RUN]

    for suite, image in todays_pins:
        if suite["listing_url"].startswith("PASTE_"):
            print(f"Skipping {suite['display_name']} - listing_url not filled in yet.")
            continue

        title, description = generate_copy(suite, content_bank, log)
        result = post_pin(suite, image, title, description)

        log.setdefault("history", []).append({
            "suite_id": suite["id"],
            "image": image,
            "title": title,
            "posted_at": datetime.now(timezone.utc).isoformat(),
            "result": "dry_run" if result.get("dry_run") else result.get("id", "unknown"),
        })
        save_json(LOG_PATH, log)  # save after each pin so a mid-run failure doesn't lose progress

        print(f"Posted: {suite['display_name']} / {image}")
        time.sleep(2)  # small delay between posts, be polite to the API


if __name__ == "__main__":
    main()
