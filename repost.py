import json
import os
import random
import sys
import time

import requests

TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL"]
STAGING = os.environ["STAGING_CHAT"]  # آیدی عددی چت خصوصی خودت با ربات
MIN_ID = 2811        # اولین پستی که وارد قرعه‌کشی می‌شه
MIN_TEXT_LEN = 100   # حداقل طول متن/کپشن برای اینکه پست «منسجم» حساب بشه
MAX_ATTEMPTS = 40
STATE_FILE = "state.json"

API = f"https://api.telegram.org/bot{TOKEN}"


class RateLimited(Exception):
    pass


def call(method, payload):
    res = {}
    for _ in range(2):
        res = requests.post(f"{API}/{method}", json=payload, timeout=30).json()
        if res.get("error_code") == 429:
            wait = res.get("parameters", {}).get("retry_after", 5)
            time.sleep(min(wait, 30) + 1)
            continue
        break
    return res


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


def inspect(message_id):
    """پیام رو بی‌صدا به چت آزمایشی فوروارد می‌کنه تا نوعش معلوم بشه، بعد پاکش می‌کنه."""
    res = call(
        "forwardMessage",
        {
            "chat_id": STAGING,
            "from_chat_id": CHANNEL,
            "message_id": message_id,
            "disable_notification": True,
        },
    )
    time.sleep(1.1)
    if res.get("error_code") == 429:
        raise RateLimited()
    if not res.get("ok"):
        return None
    m = res["result"]
    call("deleteMessage", {"chat_id": STAGING, "message_id": m["message_id"]})
    return {
        "group": m.get("media_group_id"),
        "text_len": len(m.get("text") or m.get("caption") or ""),
    }


def collect_group(message_id, info):
    """بقیه‌ی عضوهای آلبوم رو پیدا می‌کنه (آلبوم‌ها پیام‌های پشت‌سرهم با یک media_group_id هستن)."""
    ids = [message_id]
    longest = info["text_len"]
    for step in (-1, 1):
        i = message_id + step
        while len(ids) < 10 and i >= 1:
            other = inspect(i)
            if not other or other["group"] != info["group"]:
                break
            ids.append(i)
            longest = max(longest, other["text_len"])
            i += step
    return sorted(ids), longest


def evaluate(message_id):
    """برمی‌گردونه (شماره‌ها، منسجم بودن) یا None اگه پیام قابل فوروارد نیست."""
    info = inspect(message_id)
    if info is None:
        return None
    if info["group"]:
        ids, longest = collect_group(message_id, info)
    else:
        ids, longest = [message_id], info["text_len"]
    return ids, longest >= MIN_TEXT_LEN


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
        if message_id in sent or message_id in bad:
            continue  # قبلا به‌عنوان عضو یک آلبوم بررسی شده
        try:
            result = evaluate(message_id)
        except RateLimited:
            print("محدودیت نرخ تلگرام؛ بعدا دوباره اجرا کن.")
            break
        if result is None:
            bad.add(message_id)  # حذف‌شده، پیام سرویسی و ...
            continue
        ids, coherent = result
        if not coherent:
            print(f"رد شد (بدون متن کافی): {ids}")
            bad.update(ids)
            continue

        res = call(
            "forwardMessages",
            {
                "chat_id": CHANNEL,
                "from_chat_id": CHANNEL,
                "message_ids": ids,
                "disable_notification": True,
            },
        )
        if res.get("ok"):
            sent.update(ids)
            bot.update(m["message_id"] for m in res["result"])
            save_state(sent, bad, bot)
            print(f"OK: پست {ids} فوروارد شد")
            return
        print(f"فوروارد {ids} ناموفق بود: {res.get('description', '')}")
        if res.get("error_code") == 429:
            break
        bad.update(ids)

    save_state(sent, bad, bot)
    print("هیچ پستی فرستاده نشد.")
    sys.exit(1)


if __name__ == "__main__":
    main()
