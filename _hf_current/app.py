"""
TEMP MAIL PRO — Telegram Bot (Webhook Mode) + Flask API
HF Spaces can't poll api.telegram.org, so we use webhook.
"""

import os
import json
import time
import logging
import requests
import urllib3
from threading import Thread
from datetime import datetime

from flask import Flask, jsonify, request
from dotenv import load_dotenv

load_dotenv()
urllib3.disable_warnings()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

from bot.database import db
from services.email_service import email_service, TempEmail
from utils.cache import cache

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
WORKER_URL = os.getenv("CLOUDFLARE_WORKER_URL", "").rstrip("/")
WORKER_KEY = os.getenv("WORKER_API_KEY", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
TG_TIMEOUT = 30


# ═══════════════ TELEGRAM API ═══════════════

def tg_api(method, data=None, timeout=TG_TIMEOUT):
    """Call Telegram Bot API (via Worker proxy to avoid HF Spaces network issues)"""
    payload = json.dumps(data or {})
    
    # Try Worker proxy first (HF Spaces can reach Worker)
    if WORKER_URL:
        try:
            resp = requests.post(
                f"{WORKER_URL}/telegram/{method}",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": WORKER_KEY,
                    "X-Bot-Token": BOT_TOKEN,
                },
                timeout=timeout,
            )
            result = resp.json()
            if not result.get("ok"):
                logger.warning(f"TG API {method} via Worker failed: {result}")
            return result
        except Exception as e:
            logger.warning(f"TG API {method} via Worker error: {e}, trying direct...")
    
    # Fallback: direct call (may timeout on HF Spaces)
    try:
        resp = requests.post(f"{API_BASE}/{method}", data=payload, headers={"Content-Type": "application/json"}, timeout=timeout)
        result = resp.json()
        if not result.get("ok"):
            logger.warning(f"TG API {method} direct failed: {result}")
        return result
    except Exception as e:
        logger.error(f"TG API {method} error: {e}")
        return {"ok": False, "error": str(e)}


def btn(text, callback_data=None, url=None):
    b = {"text": text}
    if callback_data:
        b["callback_data"] = callback_data
    if url:
        b["url"] = url
    return b


def kb(rows):
    return {"inline_keyboard": rows}


# ═══════════════ UPDATE HANDLER ═══════════════

def process_update(update):
    """Process a Telegram update"""
    try:
        if "callback_query" in update:
            cq = update["callback_query"]
            uid = cq["from"]["id"]
            data = cq.get("data", "")
            chat = cq["message"]["chat"]["id"]
            mid = cq["message"]["message_id"]
            cqid = cq["id"]
            username = cq["from"].get("username", "")

            logger.info(f"CB: user={uid} data={data}")
            tg_api("answerCallbackQuery", {"callback_query_id": cqid})

            if data == "main_menu":
                send_menu(chat, uid, mid)
            elif data == "create_email":
                do_create_email(chat, uid, mid)
            elif data == "my_tokens":
                do_my_tokens(chat, uid, mid)
            elif data == "tasks_menu":
                do_tasks_menu(chat, uid, mid)
            elif data == "task_video":
                do_task_video(chat, mid)
            elif data == "verify_video":
                do_verify_video(chat, uid, mid)
            elif data == "task_game":
                do_task_game(chat, uid, mid)
            elif data == "task_offers":
                do_task_offers(chat, uid, mid)
            elif data == "task_referral":
                do_task_referral(chat, uid, mid, username)
            elif data == "premium":
                do_premium(chat, mid)
            elif data.startswith("inbox_"):
                do_inbox(chat, uid, mid, data[6:])
            else:
                tg_api("answerCallbackQuery", {"callback_query_id": cqid, "text": "⚠️ Đang phát triển", "show_alert": True})

        elif "message" in update:
            msg = update["message"]
            text = msg.get("text", "")
            chat = msg["chat"]["id"]
            uid = msg["from"]["id"]

            if text.startswith("/start"):
                parts = text.split()
                if len(parts) > 1:
                    do_referral(uid, parts[1], msg["from"].get("first_name", ""), chat)
                send_menu(chat, uid)
                logger.info(f"/start from {uid}")

    except Exception as e:
        logger.error(f"process_update error: {e}", exc_info=True)


# ═══════════════ HANDLERS ═══════════════

def send_menu(chat, uid, mid=None):
    user = db.get_user(uid)
    from bot.messages import WELCOME_MESSAGE
    k = kb([
        [btn("📧 Tạo Email", callback_data="create_email"), btn("💎 Tokens: %d" % user['tokens'], callback_data="my_tokens")],
        [btn("🎯 Nhiệm vụ", callback_data="tasks_menu"), btn("👑 Premium", callback_data="premium")],
        [btn("👥 Mời bạn bè (+5)", callback_data="task_referral")],
    ])
    if mid:
        tg_api("editMessageText", {"chat_id": chat, "message_id": mid, "text": WELCOME_MESSAGE, "parse_mode": "HTML", "reply_markup": k})
    else:
        tg_api("sendMessage", {"chat_id": chat, "text": WELCOME_MESSAGE, "parse_mode": "HTML", "reply_markup": k})


def do_create_email(chat, uid, mid):
    if not db.use_tokens(uid):
        from bot.messages import NO_TOKENS_MESSAGE
        tg_api("editMessageText", {"chat_id": chat, "message_id": mid, "text": NO_TOKENS_MESSAGE, "parse_mode": "HTML",
            "reply_markup": kb([[btn("🎯 Kiếm Tokens", callback_data="tasks_menu")], [btn("👑 Mua Premium", callback_data="premium")]])})
        return

    tg_api("editMessageText", {"chat_id": chat, "message_id": mid, "text": "⏳ Đang tạo email..."})
    try:
        email = email_service.create_email()
        cache.set(f"email:{email.address}", email, 3600)
        db.update_user(uid, emails_created=db.get_user(uid)["emails_created"] + 1)
        tokens = db.get_user(uid)["tokens"]

        text = f"✅ <b>Email đã tạo thành công!</b>\n\n📧 Email:\n<code>{email.address}</code>\n\n⏰ Hiệu lực: 1 giờ\n💎 Tokens: {tokens}"
        tg_api("editMessageText", {"chat_id": chat, "message_id": mid, "text": text, "parse_mode": "HTML",
            "reply_markup": kb([
                [btn("📨 Xem Inbox", callback_data=f"inbox_{email.address}")],
                [btn("📧 Tạo Mới", callback_data="create_email"), btn("🏠 Menu", callback_data="main_menu")],
            ])})
    except Exception as e:
        db.add_tokens(uid, 1, "refund")
        tg_api("editMessageText", {"chat_id": chat, "message_id": mid, "text": f"❌ Lỗi: {str(e)[:200]}\nToken đã hoàn lại.",
            "reply_markup": kb([[btn("🔄 Thử lại", callback_data="create_email")], [btn("🏠 Menu", callback_data="main_menu")]])})


def do_inbox(chat, uid, mid, email_addr):
    tg_api("editMessageText", {"chat_id": chat, "message_id": mid, "text": "⏳ Đang kiểm tra inbox..."})
    try:
        cached = cache.get(f"email:{email_addr}")
        email = cached if cached else TempEmail(address=email_addr)
        payload, messages = email_service.get_inbox(email)
        if payload:
            cache.set(f"payload:{email_addr}", payload, 300)

        if not messages:
            tg_api("editMessageText", {"chat_id": chat, "message_id": mid,
                "text": f"📭 <b>Inbox trống</b>\n\n<code>{email_addr}</code>\n\nNhấn Refresh.", "parse_mode": "HTML",
                "reply_markup": kb([[btn("🔄 Refresh", callback_data=f"inbox_{email_addr}")], [btn("📧 Mới", callback_data="create_email"), btn("🏠 Menu", callback_data="main_menu")]])})
            return

        lines = []
        for i, m in enumerate(messages[:10]):
            s = m.subject[:50] if m.subject else "No Subject"
            lines.append(f"📧 <b>{i+1}.</b> {s}")
            if m.sender:
                lines.append(f"   👤 <i>{m.sender[:30]}</i>")
            if m.snippet:
                lines.append(f"   └ {m.snippet[:60]}")
            lines.append("")

        text = f"📬 <b>Inbox</b> — {len(messages)} email(s)\n\n" + "\n".join(lines) + f"\n📧 <code>{email_addr}</code>"
        tg_api("editMessageText", {"chat_id": chat, "message_id": mid, "text": text[:4000], "parse_mode": "HTML",
            "reply_markup": kb([[btn("🔄 Refresh", callback_data=f"inbox_{email_addr}")], [btn("📧 Mới", callback_data="create_email"), btn("🏠 Menu", callback_data="main_menu")]])})
    except Exception as e:
        tg_api("editMessageText", {"chat_id": chat, "message_id": mid, "text": f"❌ Lỗi: {str(e)[:200]}",
            "reply_markup": kb([[btn("🔄 Thử lại", callback_data=f"inbox_{email_addr}")], [btn("🏠 Menu", callback_data="main_menu")]])})


def do_my_tokens(chat, uid, mid):
    user = db.get_user(uid)
    st = "👑 Premium" if db.is_premium(uid) else "👤 Free"
    from bot.messages import MY_TOKENS_MSG
    text = MY_TOKENS_MSG.format(status=st, tokens=user['tokens'], total_earned=user['total_earned'], emails_created=user['emails_created'], referral_count=user['referral_count'])
    tg_api("editMessageText", {"chat_id": chat, "message_id": mid, "text": text, "parse_mode": "HTML",
        "reply_markup": kb([[btn("🎯 Kiếm thêm", callback_data="tasks_menu")], [btn("👑 Premium", callback_data="premium")], [btn("◀️ Menu", callback_data="main_menu")]])})


def do_tasks_menu(chat, uid, mid):
    user = db.get_user(uid)
    from bot.messages import TASKS_MENU
    tg_api("editMessageText", {"chat_id": chat, "message_id": mid, "text": TASKS_MENU.format(tokens=user["tokens"]), "parse_mode": "HTML",
        "reply_markup": kb([
            [btn("📺 Xem Video (+2)", callback_data="task_video")],
            [btn("🎮 Chơi Game (+1-10)", callback_data="task_game")],
            [btn("📋 Offers (+5-20)", callback_data="task_offers")],
            [btn("👥 Mời Bạn (+5)", callback_data="task_referral")],
            [btn("🏠 Menu", callback_data="main_menu")],
        ])})


def do_task_video(chat, mid):
    tg_api("editMessageText", {"chat_id": chat, "message_id": mid,
        "text": "📺 <b>Xem video kiếm tokens</b>\n\n⏱️ 30 giây\n🎁 +2 tokens\n\n📺 Nhấn nút sau khi xem!",
        "parse_mode": "HTML",
        "reply_markup": kb([[btn("✅ Đã xem xong (+2)", callback_data="verify_video")], [btn("◀️ Quay lại", callback_data="tasks_menu")]])})


def do_verify_video(chat, uid, mid):
    db.add_tokens(uid, 2, "video_reward")
    user = db.get_user(uid)
    tg_api("editMessageText", {"chat_id": chat, "message_id": mid,
        "text": f"🎉 <b>+2 Tokens!</b>\n\n💎 Tokens: {user['tokens']}", "parse_mode": "HTML",
        "reply_markup": kb([[btn("📺 Xem thêm", callback_data="task_video")], [btn("📧 Tạo Email", callback_data="create_email")], [btn("🏠 Menu", callback_data="main_menu")]])})


def do_task_game(chat, uid, mid):
    import random
    tg_api("editMessageText", {"chat_id": chat, "message_id": mid, "text": "🎡 Đang quay..."})
    time.sleep(1.5)
    reward = random.choice([1, 2, 3, 5, 10])
    db.add_tokens(uid, reward, "spin_wheel")
    user = db.get_user(uid)
    tg_api("editMessageText", {"chat_id": chat, "message_id": mid,
        "text": f"🎉 <b>Chúc mừng!</b>\n\nBạn nhận: <b>{reward} tokens</b>\n💎 Tổng: {user['tokens']}", "parse_mode": "HTML",
        "reply_markup": kb([[btn("🔄 Quay lại", callback_data="task_video")], [btn("📧 Tạo Email", callback_data="create_email")], [btn("🏠 Menu", callback_data="main_menu")]])})


def do_task_offers(chat, uid, mid):
    from services.cpa_service import cpa_service
    offers = cpa_service.get_offers("US")
    if not offers:
        tg_api("editMessageText", {"chat_id": chat, "message_id": mid, "text": "Không có offers.", "reply_markup": kb([[btn("◀️", callback_data="tasks_menu")]])})
        return
    text = "📋 <b>Chọn nhiệm vụ:</b>\n\n"
    rows = []
    for o in offers:
        text += f"{o['title']} — +{o['reward']} tokens\n"
        rows.append([btn(f"{o['title']} (+{o['reward']} 🪙)", url=cpa_service.format_offer_link(o, uid))])
    rows.append([btn("✅ Đã xong", callback_data="verify_video")])
    rows.append([btn("◀️ Quay lại", callback_data="tasks_menu")])
    tg_api("editMessageText", {"chat_id": chat, "message_id": mid, "text": text, "parse_mode": "HTML", "reply_markup": kb(rows)})


def do_task_referral(chat, uid, mid, username=""):
    user = db.get_user(uid)
    bot_name = os.getenv("BOT_USERNAME", username or "RealEmail_Bot")
    ref = f"https://t.me/{bot_name}?start={user['referral_code']}"
    c = user['referral_count']
    text = f"👥 <b>Giới thiệu</b>\n\n🔗 Link:\n<code>{ref}</code>\n\n• Bạn: +5 tokens/người\n• Bạn bè: +2 tokens\n\n📊 Đã mời: {c} | Kiếm: {c*5} tokens"
    tg_api("editMessageText", {"chat_id": chat, "message_id": mid, "text": text, "parse_mode": "HTML",
        "reply_markup": kb([[btn("📤 Chia sẻ", url=f"https://t.me/share/url?url={ref}&text=TempMail miễn phí!")], [btn("◀️", callback_data="tasks_menu")]])})


def do_premium(chat, mid):
    from bot.messages import PREMIUM_INFO
    tg_api("editMessageText", {"chat_id": chat, "message_id": mid, "text": PREMIUM_INFO, "parse_mode": "HTML",
        "reply_markup": kb([[btn("🥉 1 tháng $4.99", callback_data="buy_1m")], [btn("🥈 3 tháng $12.99", callback_data="buy_3m")], [btn("🥇 1 năm $39.99", callback_data="buy_1y")], [btn("◀️", callback_data="main_menu")]])})


def do_referral(uid, code, name, chat):
    for rid, rd in db.get_all_users().items():
        if rd.get("referral_code") == code and int(rid) != uid:
            u = db.get_user(uid)
            if not u.get("referred_by"):
                db.update_user(uid, referred_by=int(rid))
                db.add_tokens(int(rid), 5, "ref")
                db.add_tokens(uid, 2, "ref")
                db.update_user(int(rid), referral_count=rd.get("referral_count", 0) + 1)
                tg_api("sendMessage", {"chat_id": int(rid), "text": f"🎉 {name} đã dùng link của bạn! +5 tokens!"})
            break


# ═══════════════ FLASK ═══════════════

flask_app = Flask(__name__)

@flask_app.route("/")
def index():
    return jsonify({"status": "running", "bot": "TempMail Bot", "mode": email_service.client_type, "webhook": bool(WEBHOOK_URL)})

@flask_app.route("/health")
def health():
    return jsonify({"status": "healthy"})

# Webhook endpoint — Telegram sends updates here
@flask_app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def webhook():
    try:
        update = request.get_json(force=True)
        # Process in background thread so webhook responds immediately
        Thread(target=process_update, args=(update,), daemon=True).start()
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return jsonify({"ok": True})

# API endpoints (backward compatible)
@flask_app.route("/api/create", methods=["POST"])
def api_create():
    try:
        email = email_service.create_email()
        cache.set(f"email:{email.address}", email, 3600)
        return jsonify({"success": True, "email": {"address": email.address, "timestamp": email.timestamp, "key": email.key}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@flask_app.route("/api/inbox/<path:addr>")
def api_inbox(addr):
    try:
        c = cache.get(f"email:{addr}")
        e = c if c else TempEmail(address=addr)
        p, m = email_service.get_inbox(e)
        if p: cache.set(f"payload:{addr}", p, 300)
        return jsonify({"success": True, "payload": p, "messages": [{"mid": x.mid, "subject": x.subject, "sender": x.sender, "date": x.date, "snippet": x.snippet} for x in m], "count": len(m)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@flask_app.route("/api/set-webhook", methods=["GET", "POST"])
def set_webhook():
    """Set webhook URL — call this after deployment"""
    url = request.args.get("url") or request.json.get("url") if request.is_json else None
    if not url:
        url = f"https://hungba23213213-tempmail-bot.hf.space/webhook/{BOT_TOKEN}"
    
    result = tg_api("setWebhook", {"url": url, "allowed_updates": json.dumps(["message", "callback_query"])}, timeout=60)
    return jsonify(result)


# ═══════════════ MAIN ═══════════════

def auto_set_webhook():
    """Auto-set webhook on startup"""
    if not BOT_TOKEN:
        return
    url = f"https://hungba23213213-tempmail-bot.hf.space/webhook/{BOT_TOKEN}"
    logger.info(f"🔗 Setting webhook: {url}")
    # Wait a bit for server to be ready
    time.sleep(5)
    for attempt in range(3):
        try:
            result = tg_api("setWebhook", {"url": url, "allowed_updates": json.dumps(["message", "callback_query"])}, timeout=60)
            if result.get("ok"):
                logger.info("✅ Webhook set successfully!")
                return
            else:
                logger.warning(f"Webhook attempt {attempt+1} failed: {result}")
        except Exception as e:
            logger.warning(f"Webhook attempt {attempt+1} error: {e}")
        time.sleep(10)
    logger.error("❌ Failed to set webhook after 3 attempts")


if __name__ == "__main__":
    # Auto-set webhook in background
    Thread(target=auto_set_webhook, daemon=True).start()

    port = int(os.getenv("PORT", 7860))
    logger.info(f"🚀 Flask starting on port {port}")
    flask_app.run(host="0.0.0.0", port=port, debug=False)
