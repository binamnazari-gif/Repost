import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
STATE_FILE = "state.json"
BOOKS_DIR = "books"
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def tg_request(method: str, payload: dict | None = None) -> dict:
    url = f"{API_BASE}/{method}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
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


def process_callbacks(state: dict, now: datetime) -> None:
    offset = state.get("last_update_id", 0) + 1
    try:
        res = tg_request("getUpdates", {"offset": offset, "timeout": 5})
    except Exception as e:
        print(f"Warning: getUpdates failed: {e}")
        return

    updates = res.get("result", [])
    if not updates:
        return

    for upd in updates:
        state["last_update_id"] = max(state.get("last_update_id", 0), upd["update_id"])
        cb = upd.get("callback_query")
        if not cb:
            continue

        cb_id = cb["id"]
        data = cb.get("data", "")
        parts = data.split(":")
        action = parts[0] if len(parts) > 0 else ""
        book_id = parts[1] if len(parts) > 1 else ""
        item_id = parts[2] if len(parts) > 2 else ""

        if action == "done":
            try:
                tg_request("answerCallbackQuery", {"callback_query_id": cb_id})
            except Exception:
                pass
            continue

        today_str = now.strftime("%Y-%m-%d")
        if state.get("last_active_date") != today_str:
            yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            if state.get("last_active_date") == yesterday_str:
                state["streak_days"] = state.get("streak_days", 0) + 1
            else:
                state["streak_days"] = 1
            state["last_active_date"] = today_str

        reply_text = "ثبت شد ✅"
        status_label = "✅ ثبت شد"

        if action == "know":
            state["total_mastered"] = state.get("total_mastered", 0) + 1
            state["srs_queue"] = [
                q for q in state.get("srs_queue", [])
                if not (q["book_id"] == book_id and q["item_id"] == item_id)
            ]
            reply_text = "عالی! ثبت شد به عنوان بلدم ✅"
            status_label = "✅ تسلط ثبت شد"

        elif action == "review":
            existing = next(
                (q for q in state.get("srs_queue", [])
                 if q["book_id"] == book_id and q["item_id"] == item_id),
                None,
            )
            if existing:
                next_interval = min(existing["interval_days"] * 2 + 1, 14)
                existing["interval_days"] = next_interval
                existing["next_review_at"] = (now + timedelta(days=next_interval)).isoformat()
            else:
                state.setdefault("srs_queue", []).append({
                    "book_id": book_id,
                    "item_id": item_id,
                    "interval_days": 1,
                    "next_review_at": (now + timedelta(days=1)).isoformat(),
                })
            state["total_reviewed"] = state.get("total_reviewed", 0) + 1
            reply_text = "به صف مرور اضافه شد 🔁"
            status_label = "🔁 در صف مرور ثبت شد"

        elif action == "skip5":
            state["current_item_index"] = state.get("current_item_index", 0) + 5
            reply_text = "۵ مورد بعدی رد شد ⚡"
            status_label = "⚡ ۵ مورد بعدی رد شد"

        # Acknowledge callback (may expire if clicked long ago, so ignore errors)
        try:
            tg_request("answerCallbackQuery", {
                "callback_query_id": cb_id,
                "text": reply_text,
                "show_alert": False,
            })
        except Exception:
            pass

        # Update buttons on the original message so it stays in chat and shows confirmation
        msg = cb.get("message")
        if msg:
            try:
                tg_request("editMessageReplyMarkup", {
                    "chat_id": msg["chat"]["id"],
                    "message_id": msg["message_id"],
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": status_label, "callback_data": "done"}]
                        ]
                    },
                })
            except Exception as e:
                print(f"Warning: editMessageReplyMarkup failed: {e}")


def get_next_payload(state: dict, now: datetime) -> tuple[dict | None, dict | None, bool]:
    srs_queue = state.get("srs_queue", [])
    for q in srs_queue:
        due_dt = datetime.fromisoformat(q["next_review_at"])
        if due_dt <= now:
            for bfile in state.get("book_queue", []):
                path = os.path.join(BOOKS_DIR, bfile)
                if not os.path.exists(path):
                    continue
                book = load_json(path)
                if book["book_id"] == q["book_id"]:
                    for item in book.get("items", []):
                        if item["id"] == q["item_id"]:
                            q["next_review_at"] = (now + timedelta(days=q["interval_days"])).isoformat()
                            return book, item, True

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
            return book, item, False
        else:
            if book["book_id"] not in state.get("completed_books", []):
                state.setdefault("completed_books", []).append(book["book_id"])
            b_idx += 1
            i_idx = 0

    state["current_book_index"] = b_idx
    state["current_item_index"] = i_idx
    return None, None, False


def format_message(book: dict, item: dict, is_review: bool, state: dict) -> str:
    tag = "🔁 <b>مرور هوشمند (SRS)</b>" if is_review else "⚡ <b>بمباران جدید</b>"
    streak = state.get("streak_days", 0)
    mastered = state.get("total_mastered", 0)

    header = (
        f"{tag} | 📘 <b>{escape_html(book['title'])}</b> ({escape_html(book['level'])})\n"
        f"📂 {escape_html(item.get('unit', ''))} — {escape_html(item.get('topic', ''))}\n"
        f"🔥 استریک: {streak} روز | ✅ تسلط: {mastered}\n"
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

    process_callbacks(state, now)

    book, item, is_review = get_next_payload(state, now)
    if not book or not item:
        tg_request("sendMessage", {
            "chat_id": CHAT_ID,
            "text": "🎉 تبریک! تمام کتاب‌های فعلی در صف تمام شدند. یک فایل JSON جدید به پوشه books اضافه کن!",
        })
        save_json(STATE_FILE, state)
        return

    text = format_message(book, item, is_review, state)
    b_id = book["book_id"]
    i_id = item["id"]

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ بلدم", "callback_data": f"know:{b_id}:{i_id}"},
                {"text": "🔁 مرور کن", "callback_data": f"review:{b_id}:{i_id}"},
            ],
            [
                {"text": "⚡ ۵ تای بعدی رو رد کن", "callback_data": f"skip5:{b_id}:{i_id}"},
            ],
        ]
    }

    tg_request("sendMessage", {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": keyboard,
    })

    save_json(STATE_FILE, state)
    print(f"Sent {b_id}:{i_id} (review={is_review})")


if __name__ == "__main__":
    main()