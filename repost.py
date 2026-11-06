import json
import os
import random
import sys

import requests

TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
MIN_ID = 2811  # اولین پستی که وارد قرعه‌کشی می‌شه (شماره‌ی پست تو لینکش)
MODE = os.environ.get("MODE", "copy")  # copy | forward
MAX_ATTEMPTS = 60
STATE_FILE = "state.json"

API = f"https://api.telegram.org/bot{TOKEN}"
METHOD = "forwardMessage" if MODE == "forward" else "copyMessage"


def call(method, payload):
    r = requests.post(f"{API}/{method}", json=payload, timeout=30)
    return r.json()


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return set(d.get("sent", [])), set(d.get("bad", [])), set(d.get("bot", []))
    except FileNotFoundError:
        return set(), set(), set()


def save_state(sent, bad, bot):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"sent": sorted(sent), "bad": sorted(bad), "bot": sorted(bot)}, f
        )


def get_latest_id():
    """یک پیام موقت و بی‌صدا می‌فرسته و فوری حذفش می‌کنه تا شماره‌ی آخرین پست رو بفهمه."""
    res = call(
        "sendMessage",
        {"chat_id": CHANNEL, "text": ".", "disable_notification": True},
    )
    if not res.get("ok"):
        print("پیام موقت فرستاده نشد:", res.get("description"))
        return None, None
    temp_id = res["result"]["message_id"]
    d = call("deleteMessage", {"chat_id": CHANNEL, "message_id": temp_id})
    if not d.get("ok"):
        print("هشدار: پیام موقت حذف نشد:", d.get("description"))
    return temp_id - 1, temp_id


def main():
    sent, bad, bot = load_state()

    latest, temp_id = get_latest_id()
    if latest is None or latest < MIN_ID:
        print("شماره‌ی آخرین پست مشخص نشد.")
        sys.exit(1)
    bot.add(temp_id)

    # پیام‌هایی که خود ربات فرستاده از قرعه‌کشی حذف می‌شن
    all_ids = set(range(MIN_ID, latest + 1)) - bot
    candidates = list(all_ids - sent - bad)
    if not candidates:
        # همه‌ی پست‌ها یک بار فرستاده شدن؛ از اول شروع می‌کنیم
        sent.clear()
        candidates = list(all_ids - bad)
    random.shuffle(candidates)

    for message_id in candidates[:MAX_ATTEMPTS]:
        res = call(
            METHOD,
            {
                "chat_id": CHANNEL,
                "from_chat_id": CHANNEL,
                "message_id": message_id,
                "disable_notification": True,
            },
        )
        if res.get("ok"):
            sent.add(message_id)
            bot.add(res["result"]["message_id"])
            save_state(sent, bad, bot)
            print(f"OK: پست {message_id} فرستاده شد")
            return
        print(f"پست {message_id} رد شد: {res.get('description', '')}")
        if res.get("error_code") == 429:
            print("محدودیت نرخ تلگرام؛ بعدا دوباره اجرا کن.")
            break
        # پیام حذف‌شده، پیام سرویسی، نظرسنجی کوییزی و ... قابل کپی نیستن
        bad.add(message_id)

    save_state(sent, bad, bot)
    print("هیچ پستی فرستاده نشد.")
    sys.exit(1)


if __name__ == "__main__":
    main()
