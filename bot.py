import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
STATE_FILE = "state.json"
BOOKS_DIR = "books"
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def tg_request(method: str, payload: dict) -> dict:
    url = f"{API_BASE}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def get_next_item(state: dict) -> tuple[dict | None, dict | None]:
    book_queue = state.get("book_queue", [])
    b_idx = state.get("current_book_index", 0)
    i_idx = state.get("current_item_index", 0)

    while b_idx < len(book_queue):
        bfile = book_queue[b_idx]
        path = os.path.join(BOOKS_DIR, bfile)
        if not os.path.exists(path):
            b_idx += 1
            i_idx = 0
            continue

        book = load_json(path)
        items = book.get("items", [])
        if i_idx < len(items):
            item = items[i_idx]
            state["current_book_index"] = b_idx
            state["current_item_index"] = i_idx + 1
            return book, item
        else:
            if book["book_id"] not in state.get("completed_books", []):
                state.setdefault("completed_books", []).append(book["book_id"])
            b_idx += 1
            i_idx = 0

    state["current_book_index"] = b_idx
    state["current_item_index"] = i_idx
    return None, None


def format_message(book: dict, item: dict, state: dict) -> str:
    total_sent = state.get("total_mastered", 0) + 1
    streak = state.get("streak_days", 1)

    header = (
        f"⚡ <b>بمباران انگلیسی</b> | 📘 <b>{escape_html(book['title'])}</b> ({escape_html(book['level'])})\n"
        f"📂 {escape_html(item.get('unit', ''))} — {escape_html(item.get('topic', ''))}\n"
        f"🔥 استریک: {streak} روز | 📨 ارسال‌شده: {total_sent}\n"
        f"──────────────\n"
    )

    body = f"{escape_html(item['text'])}\n\n"

    notes = item.get("notes", [])
    if notes:
        body += "💡 <b>نکات کلیدی:</b>\n"
        for n in notes:
            body += f"• {escape_html(n)}\n"
        body += "\n"

    fa = item.get("fa_translation", "")
    if fa:
        body += f"👀 <b>ترجمه (برای دیدن ضربه بزن):</b>\n<tg-spoiler>{escape_html(fa)}</tg-spoiler>"

    return header + body


def main() -> None:
    now = datetime.now(timezone.utc)
    state = load_json(STATE_FILE)

    today_str = now.strftime("%Y-%m-%d")
    if state.get("last_active_date") != today_str:
        yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        if state.get("last_active_date") == yesterday_str:
            state["streak_days"] = state.get("streak_days", 0) + 1
        else:
            state["streak_days"] = 1
        state["last_active_date"] = today_str

    book, item = get_next_item(state)
    if not book or not item:
        tg_request("sendMessage", {
            "chat_id": CHAT_ID,
            "text": "🎉 تمام کتاب‌های فعلی تمام شدند! فایل کتاب جدید را در پوشه books قرار بده.",
        })
        save_json(STATE_FILE, state)
        return

    text = format_message(book, item, state)
    tg_request("sendMessage", {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    })

    state["total_mastered"] = state.get("total_mastered", 0) + 1
    save_json(STATE_FILE, state)
    print(f"Sent {book['book_id']}:{item['id']}")


if __name__ == "__main__":
    main()