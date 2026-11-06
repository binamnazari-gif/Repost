"""
هر بار که اجرا بشه، یک پست تصادفی از آرشیو کانال رو دوباره در کانال می‌فرسته.

متغیرهای محیطی لازم:
  BOT_TOKEN : توکن ربات از BotFather
  CHANNEL   : یوزرنیم کانال (مثلا @my_channel) یا آیدی عددی (-100...)
  MAX_ID    : شماره‌ی آخرین پست کانال (از لینک پست: t.me/my_channel/123 -> 123)

اختیاری:
  MODE      : copy (پیش‌فرض، بدون برچسب Forwarded) یا forward
  MIN_ID    : شماره‌ی اولین پستی که می‌خوای در قرعه‌کشی باشه (پیش‌فرض 1)
"""
import json
import os
import random
import sys

import requests

TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
MAX_ID = int(os.environ["MAX_ID"])
MIN_ID = int(os.environ.get("MIN_ID", "1"))
MODE = os.environ.get("MODE", "copy")  # copy | forward
MAX_ATTEMPTS = 60
STATE_FILE = "state.json"

API = f"https://api.telegram.org/bot{TOKEN}"
METHOD = "forwardMessage" if MODE == "forward" else "copyMessage"


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("sent", [])), set(data.get("bad", []))
    except FileNotFoundError:
        return set(), set()


def save_state(sent, bad):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"sent": sorted(sent), "bad": sorted(bad)}, f)


def try_send(message_id):
    r = requests.post(
        f"{API}/{METHOD}",
        json={
            "chat_id": CHANNEL,
            "from_chat_id": CHANNEL,
            "message_id": message_id,
            "disable_notification": True,
        },
        timeout=30,
    )
    return r.json()


def main():
    sent, bad = load_state()
    all_ids = set(range(MIN_ID, MAX_ID + 1))

    candidates = list(all_ids - sent - bad)
    if not candidates:
        # همه‌ی پست‌ها یک بار فرستاده شدن؛ از اول شروع می‌کنیم
        sent.clear()
        candidates = list(all_ids - bad)
    random.shuffle(candidates)

    for message_id in candidates[:MAX_ATTEMPTS]:
        res = try_send(message_id)
        if res.get("ok"):
            sent.add(message_id)
            save_state(sent, bad)
            print(f"OK: پست {message_id} فرستاده شد")
            return
        desc = res.get("description", "")
        print(f"پست {message_id} رد شد: {desc}")
        if res.get("error_code") == 429:
            print("محدودیت نرخ تلگرام؛ بعدا دوباره اجرا کن.")
            break
        # پیام حذف‌شده، پیام سرویسی، نظرسنجی کوییزی و ... قابل کپی نیستن
        bad.add(message_id)

    save_state(sent, bad)
    print("هیچ پستی فرستاده نشد.")
    sys.exit(1)


if __name__ == "__main__":
    main()
