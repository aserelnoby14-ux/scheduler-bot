import os
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

BOT_TOKEN = os.environ["BOT_TOKEN"].strip()
ADMIN_ID = int(os.environ["ADMIN_ID"])
CHANNEL_ID = os.environ.get("CHANNEL_ID", "").strip()
SUPPORT_URL = os.environ.get("SUPPORT_URL", "https://example.com").strip()
DEV_URL = os.environ.get("DEV_URL", "https://t.me/Asernoby23").strip()
PUBLISH_INTERVAL_HOURS = int(os.environ.get("PUBLISH_INTERVAL_HOURS", "12"))

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
STATE_PATH = Path("data/state.json")
PUBLISH_TARGET = CHANNEL_ID if CHANNEL_ID else str(ADMIN_ID)

MEDIA_FIELDS = {
    "document": "sendDocument",
    "video": "sendVideo",
    "audio": "sendAudio",
    "photo": "sendPhoto",
    "animation": "sendAnimation",
    "voice": "sendVoice",
}


def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"offset": 0, "last_publish": None, "queue": []}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def tg(method, **params):
    try:
        r = requests.post(f"{API}/{method}", json=params, timeout=30)
        data = r.json()
        if not data.get("ok"):
            log.error("telegram error %s: %s", method, data)
        return data
    except Exception as e:
        log.exception("tg request failed: %s", method)
        return {"ok": False, "error": str(e)}


def get_updates(offset):
    try:
        r = requests.get(
            f"{API}/getUpdates",
            params={"offset": offset, "timeout": 0, "allowed_updates": '["message"]'},
            timeout=30,
        )
        return r.json().get("result", [])
    except Exception:
        log.exception("getUpdates failed")
        return []


def keyboard():
    return {
        "inline_keyboard": [[
            {"text": "📢 ادعمني", "url": SUPPORT_URL},
            {"text": "👨‍💻 مطور البوت", "url": DEV_URL},
        ]]
    }


def reply(chat_id, text, with_keyboard=False):
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if with_keyboard:
        params["reply_markup"] = keyboard()
    tg("sendMessage", **params)


def extract_media(msg):
    for field, method in MEDIA_FIELDS.items():
        if field in msg:
            obj = msg[field]
            if field == "photo":
                obj = obj[-1]
            return {
                "file_id": obj["file_id"],
                "method": method,
                "caption": msg.get("caption", ""),
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
            }
    return None


def handle_update(update, state):
    msg = update.get("message")
    if not msg:
        return

    chat_id = msg["chat"]["id"]
    from_id = msg.get("from", {}).get("id")
    text = (msg.get("text") or "").strip()
    is_admin = from_id == ADMIN_ID

    if text == "/start":
        if is_admin:
            reply(chat_id,
                "👋 أهلاً يا أدمن\n\n"
                "📤 ابعت أي ملف (فيديو/صورة/مستند/صوت) وأنا هجدوله.\n"
                f"⏰ كل ملف هينشر كل <b>{PUBLISH_INTERVAL_HOURS} ساعة</b>.\n\n"
                "الأوامر:\n"
                "/queue — عرض القائمة\n"
                "/publish — نشر فوري للتالي\n"
                "/status — حالة البوت\n"
                "/clear — مسح كل الملفات"
            )
        else:
            reply(chat_id, "👋 أهلاً بيك!\nاستخدم الأزرار تحت.", with_keyboard=True)
        return

    if not is_admin:
        reply(chat_id, "⛔ غير مصرح لك.", with_keyboard=True)
        return

    if text == "/queue":
        q = state["queue"]
        if not q:
            reply(chat_id, "📭 القائمة فاضية.")
            return
        lines = [f"📋 <b>{len(q)} ملف:</b>\n"]
        for i, item in enumerate(q[:20], 1):
            cap = (item.get("caption") or "")[:50] or "(بدون وصف)"
            lines.append(f"{i}. {item['method'].replace('send', '')} — {cap}")
        if len(q) > 20:
            lines.append(f"\n... و {len(q) - 20} كمان")
        reply(chat_id, "\n".join(lines))
        return

    if text == "/status":
        last = state.get("last_publish")
        if last:
            try:
                dt = datetime.fromisoformat(last)
                next_dt = dt + timedelta(hours=PUBLISH_INTERVAL_HOURS)
                remaining = next_dt - datetime.now(timezone.utc)
                last_str = dt.strftime("%Y-%m-%d %H:%M UTC")
                next_str = next_dt.strftime("%Y-%m-%d %H:%M UTC")
                rem_str = str(remaining).split(".")[0] if remaining.total_seconds() > 0 else "جاهز للنشر"
            except Exception:
                last_str, next_str, rem_str = last, "-", "-"
        else:
            last_str, next_str, rem_str = "لسه ما نشرش", "-", "جاهز للنشر"

        reply(chat_id,
            f"📊 <b>حالة البوت</b>\n\n"
            f"📤 آخر نشر: {last_str}\n"
            f"⏭️ النشر التالي: {next_str}\n"
            f"⏳ متبقي: {rem_str}\n"
            f"📋 في القائمة: <b>{len(state['queue'])}</b> ملف\n"
            f"🎯 هدف النشر: <code>{PUBLISH_TARGET}</code>"
        )
        return

    if text == "/publish":
        if not state["queue"]:
            reply(chat_id, "📭 القائمة فاضية.")
            return
        if publish_next(state):
            reply(chat_id, "✅ تم النشر الفوري.")
        else:
            reply(chat_id, "❌ فشل النشر — شوف اللوج.")
        return

    if text == "/clear":
        n = len(state["queue"])
        state["queue"] = []
        save_state(state)
        reply(chat_id, f"🗑️ تم مسح {n} ملف.")
        return

    media = extract_media(msg)
    if media:
        state["queue"].append(media)
        save_state(state)
        reply(chat_id,
            f"✅ تم استلام الملف\n"
            f"📋 في القائمة: <b>{len(state['queue'])}</b> ملف"
        )
        return

    reply(chat_id, "❓ ابعت ملف أو استخدم /status")


def publish_next(state):
    if not state["queue"]:
        return False

    item = state["queue"][0]
    method = item["method"]
    field = method.replace("send", "").lower()

    params = {
        "chat_id": PUBLISH_TARGET,
        field: item["file_id"],
        "reply_markup": keyboard(),
    }
    if item.get("caption"):
        params["caption"] = item["caption"]
        params["parse_mode"] = "HTML"

    result = tg(method, **params)

    if not result.get("ok"):
        log.error("publish failed: %s", result)
        return False

    state["queue"].pop(0)
    state["last_publish"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    log.info("published file_id=%s method=%s", item["file_id"], method)
    return True


def should_publish(state):
    if not state["queue"]:
        return False
    last = state.get("last_publish")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
    except Exception:
        return True
    return (datetime.now(timezone.utc) - last_dt) >= timedelta(hours=PUBLISH_INTERVAL_HOURS)


def main():
    state = load_state()

    updates = get_updates(state["offset"])
    log.info("got %d updates", len(updates))

    for update in updates:
        try:
            handle_update(update, state)
        except Exception:
            log.exception("update %s failed", update.get("update_id"))
        state["offset"] = update["update_id"] + 1
        save_state(state)

    if should_publish(state):
        log.info("interval reached, publishing next")
        if publish_next(state):
            reply(ADMIN_ID, "✅ تم نشر ملف جديد تلقائياً.")


if __name__ == "__main__":
    main()