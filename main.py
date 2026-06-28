"""
TempMail Pro — Telegram Bot (aiohttp async)
Uses raw requests via Worker proxy (proven to work on HF Spaces).
Same architecture as original app.py but with async I/O.
"""

import os
import json
import time
import hashlib
import logging
import asyncio
import requests
import urllib3
from aiohttp import web

from dotenv import load_dotenv
load_dotenv()
urllib3.disable_warnings()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

from bot.database import db
from services.email_service import email_service, TempEmail
from utils.cache import cache

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WORKER_URL = os.getenv("CLOUDFLARE_WORKER_URL", "").rstrip("/")
WORKER_KEY = os.getenv("WORKER_API_KEY", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
PORT = int(os.getenv("PORT", 7860))

# ═══ Monetag Ad Config ═══
AD_PUBLISHER_ID = os.getenv("AD_PUBLISHER_ID", "3387462")
AD_ZONE_ID = os.getenv("AD_ZONE_ID", "11208686")
AD_WEB_URL = os.getenv("AD_WEB_URL", "https://hungba23213213-tempmail-pro.hf.space")  # HF Space serves /watch-ad inline
AD_REWARDED_TOKENS = 2  # Tokens granted per ad view
AD_MAX_REWARDED_PER_DAY = 10  # Max ads per user per day
ad_watched_today = {}  # user_id -> count
ad_watched_last_reset = {}  # user_id -> date string


# ════════════════════════════════════════════════════════════════
#                    TELEGRAM API (via Worker)
# ════════════════════════════════════════════════════════════════

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""

# Use urllib3 pool for Worker — try HTTP first, then HTTPS
_worker_host = WORKER_URL.replace("https://", "").replace("http://", "").rstrip("/")
_worker_pool = urllib3.HTTPSConnectionPool(
    _worker_host,
    port=443,
    cert_reqs="CERT_NONE",
    maxsize=5,
)
_worker_http_pool = urllib3.HTTPConnectionPool(
    _worker_host,
    port=80,
    maxsize=5,
)


def tg_api(method, data=None, timeout=15):
    """Call Telegram Bot API. Try HTTP Worker → HTTPS Worker → Direct."""
    payload = json.dumps(data or {})
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": WORKER_KEY,
        "X-Bot-Token": BOT_TOKEN,
    }
    
    # Try HTTP Worker first (no SSL issues)
    if WORKER_URL:
        try:
            resp = _worker_http_pool.request(
                "POST", f"/telegram/{method}",
                body=payload, headers=headers, timeout=timeout,
            )
            return json.loads(resp.data.decode("utf-8"))
        except Exception as e1:
            logger.warning(f"TG {method} HTTP Worker: {e1}")
        
        # Try HTTPS Worker
        try:
            resp = _worker_pool.request(
                "POST", f"/telegram/{method}",
                body=payload, headers=headers, timeout=timeout,
            )
            return json.loads(resp.data.decode("utf-8"))
        except Exception as e2:
            logger.warning(f"TG {method} HTTPS Worker: {e2}")
    
    # Fallback: direct
    try:
        resp = requests.post(
            f"{API_BASE}/{method}",
            data=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        return resp.json()
    except Exception as e3:
        logger.error(f"TG {method} direct failed: {e3}")
    
    return {"ok": False, "error": "All methods failed"}


async def tg_api_async(method, data=None, timeout=15):
    """Async wrapper for tg_api."""
    return await asyncio.to_thread(tg_api, method, data, timeout)


def btn(text, callback_data=None, url=None, web_app=None):
    b = {"text": text}
    if callback_data:
        b["callback_data"] = callback_data
    if url:
        b["url"] = url
    if web_app:
        b["web_app"] = {"url": web_app}
    return b


def kb(rows):
    return {"inline_keyboard": rows}


# ════════════════════════════════════════════════════════════════
#                         HANDLERS
# ════════════════════════════════════════════════════════════════

async def process_update(update):
    """Process a Telegram update (async)."""
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
            await tg_api_async("answerCallbackQuery", {"callback_query_id": cqid})

            if data == "main_menu":
                await send_menu(chat, uid, mid)
            elif data == "create_email":
                await do_create_email(chat, uid, mid)
            elif data == "my_tokens":
                await do_my_tokens(chat, uid, mid)
            elif data == "tasks_menu":
                await do_tasks_menu(chat, uid, mid)
            elif data == "task_video":
                await do_task_video(chat, uid, mid)
            elif data == "verify_video":
                await do_verify_video(chat, uid, mid)
            elif data == "task_game":
                await do_task_game(chat, uid, mid)
            elif data == "task_offers":
                await do_task_offers(chat, uid, mid)
            elif data == "task_referral":
                await do_task_referral(chat, uid, mid, username)
            elif data == "premium":
                await do_premium(chat, mid)
            elif data.startswith("inbox_"):
                await do_inbox(chat, uid, mid, data[6:])
            elif data.startswith("msg_"):
                # Format: msg_{mid}_{email_addr}
                parts = data[4:].split("_", 1)
                if len(parts) == 2:
                    await do_read_message(chat, mid, parts[0], parts[1])
            elif data == "my_emails":
                await do_my_emails(chat, uid, mid)
            elif data.startswith("return_"):
                email_addr = data[7:]
                await do_return_email(chat, uid, mid, email_addr)
            elif data.startswith("verify_return_"):
                email_addr = data[14:]
                await do_verify_return(chat, uid, mid, email_addr)
            else:
                await tg_api_async("answerCallbackQuery", {
                    "callback_query_id": cqid,
                    "text": "⚠️ Đang phát triển",
                    "show_alert": True,
                })

        elif "message" in update:
            msg = update["message"]
            text = msg.get("text", "")
            chat = msg["chat"]["id"]
            uid = msg["from"]["id"]

            # Handle Web App data (Monetag ad completion callback)
            if "web_app_data" in msg:
                web_data = msg["web_app_data"].get("data", "")
                logger.info(f"WebApp data from {uid}: {web_data}")
                try:
                    payload = json.loads(web_data)
                    if payload.get("action") == "ad_completed":
                        ad_token = payload.get("token", "")
                        await handle_ad_reward(chat, uid, ad_token)
                except (json.JSONDecodeError, Exception) as e:
                    logger.error(f"WebApp data error: {e}")
                return

            if text.startswith("/start"):
                parts = text.split()
                if len(parts) > 1:
                    await do_referral(uid, parts[1], msg["from"].get("first_name", ""), chat)
                logger.info(f"/start from {uid}")
                await send_menu(chat, uid)

    except Exception as e:
        logger.error(f"process_update error: {e}", exc_info=True)


# ── /start menu ──

async def send_menu(chat, uid, mid=None):
    user = db.get_user(uid)
    from bot.messages import WELCOME_FIRST, MENU_MESSAGE
    is_new = not user.get("seen_welcome", True)

    k = kb([
        [btn("📧 Tạo Email", callback_data="create_email"),
         btn("💎 Tokens: %d" % user["tokens"], callback_data="my_tokens")],
        [btn("📬 My Emails", callback_data="my_emails"),
         btn("🎯 Nhiệm vụ", callback_data="tasks_menu")],
        [btn("👑 Premium", callback_data="premium"),
         btn("👥 Mời bạn (+5)", callback_data="task_referral")],
    ])

    menu_text = MENU_MESSAGE.format(tokens=user["tokens"])

    if is_new:
        # First time: send welcome, then menu
        db.update_user(uid, seen_welcome=True)
        await tg_api_async("sendMessage", {
            "chat_id": chat,
            "text": WELCOME_FIRST, "parse_mode": "Markdown",
        })
        await tg_api_async("sendMessage", {
            "chat_id": chat,
            "text": menu_text, "parse_mode": "HTML", "reply_markup": k,
        })
    elif mid:
        # Editing existing message (from callback)
        await tg_api_async("editMessageText", {
            "chat_id": chat, "message_id": mid,
            "text": menu_text, "parse_mode": "HTML", "reply_markup": k,
        })
    else:
        # Returning user, new message
        await tg_api_async("sendMessage", {
            "chat_id": chat,
            "text": menu_text, "parse_mode": "HTML", "reply_markup": k,
        })


# ── Create email ──

async def do_create_email(chat, uid, mid):
    if not db.use_tokens(uid):
        from bot.messages import NO_TOKENS_MESSAGE
        await tg_api_async("editMessageText", {
            "chat_id": chat, "message_id": mid,
            "text": NO_TOKENS_MESSAGE, "parse_mode": "HTML",
            "reply_markup": kb([
                [btn("🎯 Kiếm Tokens", callback_data="tasks_menu")],
                [btn("👑 Mua Premium", callback_data="premium")],
            ]),
        })
        return

    # Show loading (no buttons = disabled)
    await tg_api_async("editMessageText", {"chat_id": chat, "message_id": mid, "text": "⏳ Đang tạo email..."})
    try:
        email = await asyncio.to_thread(email_service.create_email)
        cache.set(f"email:{email.address}", email, 3600)
        db.update_user(uid, emails_created=db.get_user(uid)["emails_created"] + 1)
        db.add_email(uid, email.address, email.timestamp, email.key)  # Save to history
        tokens = db.get_user(uid)["tokens"]

        text = f"✅ <b>Email đã tạo thành công!</b>\n\n📧 Email:\n<code>{email.address}</code>\n\n⏰ Hiệu lực: 5 phút\n💎 Tokens: {tokens}"
        await tg_api_async("editMessageText", {
            "chat_id": chat, "message_id": mid,
            "text": text, "parse_mode": "HTML",
            "reply_markup": kb([
                [btn("📨 Xem Inbox", callback_data=f"inbox_{email.address}")],
                [btn("📧 Tạo Mới", callback_data="create_email"),
                 btn("🏠 Menu", callback_data="main_menu")],
            ]),
        })
    except Exception as e:
        db.add_tokens(uid, 1, "refund")
        await tg_api_async("editMessageText", {
            "chat_id": chat, "message_id": mid,
            "text": f"❌ Lỗi: {str(e)[:200]}\nToken đã hoàn lại.",
            "reply_markup": kb([
                [btn("🔄 Thử lại", callback_data="create_email")],
                [btn("🏠 Menu", callback_data="main_menu")],
            ]),
        })


# ── Inbox ──

async def do_inbox(chat, uid, mid, email_addr):
    await tg_api_async("editMessageText", {"chat_id": chat, "message_id": mid, "text": "⏳ Đang kiểm tra inbox..."})
    try:
        cached = cache.get(f"email:{email_addr}")
        email = cached if cached else TempEmail(address=email_addr)
        payload, messages = await asyncio.to_thread(email_service.get_inbox, email)
        if payload:
            cache.set(f"payload:{email_addr}", payload, 300)

        if not messages:
            await tg_api_async("editMessageText", {
                "chat_id": chat, "message_id": mid,
                "text": f"📭 <b>Inbox trống</b>\n\n<code>{email_addr}</code>\n\nNhấn Refresh.",
                "parse_mode": "HTML",
                "reply_markup": kb([
                    [btn("🔄 Refresh", callback_data=f"inbox_{email_addr}")],
                    [btn("📧 Mới", callback_data="create_email"),
                     btn("🏠 Menu", callback_data="main_menu")],
                ]),
            })
            return

        lines = []
        msg_buttons = []
        for i, m in enumerate(messages[:10]):
            s = m.subject[:40] if m.subject else "No Subject"
            lines.append(f"📧 <b>{i+1}.</b> {s}")
            if m.sender:
                lines.append(f"   👤 <i>{m.sender[:30]}</i>")
            if m.snippet:
                lines.append(f"   └ {m.snippet[:50]}")
            lines.append("")
            # Add button for each message
            msg_buttons.append([btn(
                f"📧 {i+1}. {s[:30]}",
                callback_data=f"msg_{m.mid}_{email_addr}",
            )])

        # Cache messages for later detail lookup
        cache.set(f"messages:{email_addr}", messages, 300)

        text = f"📬 <b>Inbox</b> — {len(messages)} email(s)\n\n" + "\n".join(lines) + f"\n📧 <code>{email_addr}</code>"
        bottom_buttons = [
            [btn("🔄 Refresh", callback_data=f"inbox_{email_addr}")],
            [btn("📧 Mới", callback_data="create_email"),
             btn("🏠 Menu", callback_data="main_menu")],
        ]
        await tg_api_async("editMessageText", {
            "chat_id": chat, "message_id": mid,
            "text": text[:4000], "parse_mode": "HTML",
            "reply_markup": kb(msg_buttons + bottom_buttons),
        })
    except Exception as e:
        await tg_api_async("editMessageText", {
            "chat_id": chat, "message_id": mid,
            "text": f"❌ Lỗi: {str(e)[:200]}",
            "reply_markup": kb([
                [btn("🔄 Thử lại", callback_data=f"inbox_{email_addr}")],
                [btn("🏠 Menu", callback_data="main_menu")],
            ]),
        })


# ── Read message detail ──

async def do_read_message(chat, mid, msg_mid, email_addr):
    await tg_api_async("editMessageText", {
        "chat_id": chat, "message_id": mid,
        "text": "⏳ Đang tải nội dung email...",
    })
    try:
        # Get payload from cache
        payload = cache.get(f"payload:{email_addr}")
        if not payload:
            # Re-fetch inbox to get payload
            cached = cache.get(f"email:{email_addr}")
            email_obj = cached if cached else TempEmail(address=email_addr)
            payload, _ = await asyncio.to_thread(email_service.get_inbox, email_obj)
            if payload:
                cache.set(f"payload:{email_addr}", payload, 300)

        if not payload:
            await tg_api_async("editMessageText", {
                "chat_id": chat, "message_id": mid,
                "text": "❌ Không thể đọc email. Payload đã hết hạn.\nVui lòng tạo email mới.",
                "reply_markup": kb([
                    [btn("📧 Tạo Mới", callback_data="create_email")],
                    [btn("🏠 Menu", callback_data="main_menu")],
                ]),
            })
            return

        # Get subject/sender/date from cached inbox messages
        subject = "(No Subject)"
        sender = ""
        date_str = ""
        cached_messages = cache.get(f"messages:{email_addr}")
        if cached_messages:
            for mm in cached_messages:
                if mm.mid == msg_mid:
                    subject = mm.subject or "(No Subject)"
                    sender = mm.sender or ""
                    date_str = mm.date or ""
                    break

        # Fetch message body via Worker → Sonjj
        detail = await asyncio.to_thread(
            email_service.get_message_detail, msg_mid, payload
        )

        body = detail.body_html or ""

        # Strip HTML tags for clean display
        if body:
            import re
            body = re.sub(r'<br\s*/?>', '\n', body)
            body = re.sub(r'<[^>]+>', '', body)
            body = re.sub(r'\n{3,}', '\n\n', body).strip()

        body = body[:3000] or "(Empty)"

        text = f"📧 <b>{subject}</b>\n\n"
        if sender:
            text += f"👤 From: <i>{sender}</i>\n"
        if date_str:
            text += f"📅 Date: {date_str}\n"
        text += f"\n{body}"

        await tg_api_async("editMessageText", {
            "chat_id": chat, "message_id": mid,
            "text": text[:4000], "parse_mode": "HTML",
            "reply_markup": kb([
                [btn("◀️ Quay lại Inbox", callback_data=f"inbox_{email_addr}")],
                [btn("📧 Tạo Mới", callback_data="create_email"),
                 btn("🏠 Menu", callback_data="main_menu")],
            ]),
        })
    except Exception as e:
        logger.error(f"Read message error: {e}")
        await tg_api_async("editMessageText", {
            "chat_id": chat, "message_id": mid,
            "text": f"❌ Lỗi đọc email: {str(e)[:200]}",
            "reply_markup": kb([
                [btn("◀️ Quay lại Inbox", callback_data=f"inbox_{email_addr}")],
                [btn("🏠 Menu", callback_data="main_menu")],
            ]),
        })


# ── My Emails ──

EMAIL_EXPIRY_SECONDS = 300  # 5 minutes

async def do_my_emails(chat, uid, mid):
    """Show list of user's emails"""
    emails = db.get_emails(uid)

    if not emails:
        await tg_api_async("editMessageText", {
            "chat_id": chat, "message_id": mid,
            "text": "📭 <b>Bạn chưa có email nào!</b>\n\nNhấn Tạo Email để bắt đầu.",
            "parse_mode": "HTML",
            "reply_markup": kb([
                [btn("📧 Tạo Email", callback_data="create_email")],
                [btn("🏠 Menu", callback_data="main_menu")],
            ]),
        })
        return

    from bot.messages import EMAIL_LIST_HEADER
    text = EMAIL_LIST_HEADER.format(count=len(emails))

    now = time.time()
    email_buttons = []

    for e in emails:
        addr = e["address"]
        age = now - e.get("created_at", 0)
        remaining = max(0, int((EMAIL_EXPIRY_SECONDS - age) / 60))

        if age < EMAIL_EXPIRY_SECONDS:
            # Active
            text += f"✅ <code>{addr}</code> — còn ~{remaining + 1}p\n"
            email_buttons.append([
                btn(f"📨 {addr[:25]}", callback_data=f"inbox_{addr}"),
                btn("🔄 Return", callback_data=f"return_{addr}"),
            ])
        else:
            # Expired
            text += f"⏰ <code>{addr}</code> — hết hạn\n"
            email_buttons.append([
                btn(f"📨 {addr[:25]}", callback_data=f"inbox_{addr}"),
                btn("📺 Return (xem ads)", callback_data=f"return_{addr}"),
            ])

    email_buttons.append([btn("📧 Tạo Email Mới", callback_data="create_email")])
    email_buttons.append([btn("🏠 Menu", callback_data="main_menu")])

    await tg_api_async("editMessageText", {
        "chat_id": chat, "message_id": mid,
        "text": text[:4000], "parse_mode": "HTML",
        "reply_markup": kb(email_buttons),
    })


async def do_return_email(chat, uid, mid, email_addr):
    """Return to an email — if expired, require watching ad"""
    email_data = db.get_email_by_addr(uid, email_addr)
    if not email_data:
        await tg_api_async("editMessageText", {
            "chat_id": chat, "message_id": mid,
            "text": "❌ Email không tìm thấy.",
            "reply_markup": kb([[btn("🏠 Menu", callback_data="main_menu")]]),
        })
        return

    age = time.time() - email_data.get("created_at", 0)

    if age < EMAIL_EXPIRY_SECONDS:
        # Still active → go to inbox
        await do_inbox(chat, uid, mid, email_addr)
    else:
        # Expired → require watching ad
        watch_url = f"{AD_WEB_URL}/?uid={uid}&reward={AD_REWARDED_TOKENS}&action=return&email={email_addr}" if AD_WEB_URL else f"https://hungba23213213-tempmail-bot.hf.space/watch-ad?uid={uid}&action=return&email={email_addr}"
        
        from bot.messages import AD_REQUIRED_MSG
        await tg_api_async("editMessageText", {
            "chat_id": chat, "message_id": mid,
            "text": AD_REQUIRED_MSG.format(address=email_addr),
            "parse_mode": "HTML",
            "reply_markup": kb([
                [btn("📺 Xem Video để Return", url=watch_url)],
                [btn("◀️ Quay lại", callback_data="my_emails")],
            ]),
        })


async def do_verify_return(chat, uid, mid, email_addr):
    """After watching ad, refresh email and go to inbox"""
    # Award tokens for watching ad
    db.add_tokens(uid, 2, "watch_ad_return")

    # Update email timestamp to "refresh" it
    email_data = db.get_email_by_addr(uid, email_addr)
    if email_data:
        email_data["created_at"] = time.time()
        db._mark_dirty()

        # Also refresh cache
        cached = cache.get(f"email:{email_addr}")
        if cached:
            cache.delete(f"payload:{email_addr}")  # Reset payload cache

    # Go to inbox
    await do_inbox(chat, uid, mid, email_addr)


# ── My tokens ──

async def do_my_tokens(chat, uid, mid):
    user = db.get_user(uid)
    st = "👑 Premium" if db.is_premium(uid) else "👤 Free"
    from bot.messages import MY_TOKENS_MSG
    text = MY_TOKENS_MSG.format(
        status=st, tokens=user["tokens"],
        total_earned=user["total_earned"],
        emails_created=user["emails_created"],
        referral_count=user["referral_count"],
    )
    await tg_api_async("editMessageText", {
        "chat_id": chat, "message_id": mid,
        "text": text, "parse_mode": "HTML",
        "reply_markup": kb([
            [btn("🎯 Kiếm thêm", callback_data="tasks_menu")],
            [btn("👑 Premium", callback_data="premium")],
            [btn("◀️ Menu", callback_data="main_menu")],
        ]),
    })


# ── Tasks ──

async def do_tasks_menu(chat, uid, mid):
    user = db.get_user(uid)
    from bot.messages import TASKS_MENU
    await tg_api_async("editMessageText", {
        "chat_id": chat, "message_id": mid,
        "text": TASKS_MENU.format(tokens=user["tokens"]),
        "parse_mode": "HTML",
        "reply_markup": kb([
            [btn("📺 Xem Video (+2)", callback_data="task_video")],
            [btn("🎮 Chơi Game (+1-10)", callback_data="task_game")],
            [btn("📋 Offers (+5-20)", callback_data="task_offers")],
            [btn("👥 Mời Bạn (+5)", callback_data="task_referral")],
            [btn("🏠 Menu", callback_data="main_menu")],
        ]),
    })


async def do_task_video(chat, uid, mid):
    # Check daily limit
    today = time.strftime("%Y-%m-%d")
    if ad_watched_last_reset.get(uid) != today:
        ad_watched_today[uid] = 0
        ad_watched_last_reset[uid] = today
    
    watched = ad_watched_today.get(uid, 0)
    if watched >= AD_MAX_REWARDED_PER_DAY:
        await tg_api_async("editMessageText", {
            "chat_id": chat, "message_id": mid,
            "text": f"📺 <b>Đã đạt giới hạn {AD_MAX_REWARDED_PER_DAY} video/ngày!</b>\n\n⏰ Thử lại ngày mai.",
            "parse_mode": "HTML",
            "reply_markup": kb([
                [btn("◀️ Quay lại", callback_data="tasks_menu")],
            ]),
        })
        return
    
    # Web App button opens Monetag rewarded ad page
    watch_url = f"{AD_WEB_URL}/watch-ad?uid={uid}&reward={AD_REWARDED_TOKENS}"
    
    await tg_api_async("editMessageText", {
        "chat_id": chat, "message_id": mid,
        "text": (
            "📺 <b>Xem video kiếm tokens</b>\n\n"
            "⏱️ Chỉ mất 30 giây\n"
            f"🎁 Nhận ngay +{AD_REWARDED_TOKENS} tokens\n"
            f"📊 Hôm nay: {watched}/{AD_MAX_REWARDED_PER_DAY}\n\n"
            "👇 Nhấn nút bên dưới để xem quảng cáo!"
        ),
        "parse_mode": "HTML",
        "reply_markup": kb([
            [btn("📺 Xem Video (+2 tokens)", web_app=watch_url)],
            [btn("◀️ Quay lại", callback_data="tasks_menu")],
        ]),
    })


async def do_verify_video(chat, uid, mid):
    db.add_tokens(uid, 2, "video_reward")
    user = db.get_user(uid)
    await tg_api_async("editMessageText", {
        "chat_id": chat, "message_id": mid,
        "text": f"🎉 <b>+2 Tokens!</b>\n\n💎 Tokens: {user['tokens']}",
        "parse_mode": "HTML",
        "reply_markup": kb([
            [btn("📺 Xem thêm", callback_data="task_video")],
            [btn("📧 Tạo Email", callback_data="create_email")],
            [btn("🏠 Menu", callback_data="main_menu")],
        ]),
    })


async def do_task_game(chat, uid, mid):
    import random
    await tg_api_async("editMessageText", {"chat_id": chat, "message_id": mid, "text": "🎡 Đang quay..."})
    await asyncio.sleep(1.5)
    reward = random.choice([1, 2, 3, 5, 10])
    db.add_tokens(uid, reward, "spin_wheel")
    user = db.get_user(uid)
    await tg_api_async("editMessageText", {
        "chat_id": chat, "message_id": mid,
        "text": f"🎉 <b>Chúc mừng!</b>\n\nBạn nhận: <b>{reward} tokens</b>\n💎 Tổng: {user['tokens']}",
        "parse_mode": "HTML",
        "reply_markup": kb([
            [btn("🔄 Quay lại", callback_data="task_game")],
            [btn("📧 Tạo Email", callback_data="create_email")],
            [btn("🏠 Menu", callback_data="main_menu")],
        ]),
    })


async def do_task_offers(chat, uid, mid):
    from services.cpa_service import cpa_service
    offers = cpa_service.get_offers("US")
    if not offers:
        await tg_api_async("editMessageText", {
            "chat_id": chat, "message_id": mid,
            "text": "Không có offers.",
            "reply_markup": kb([[btn("◀️", callback_data="tasks_menu")]]),
        })
        return
    text = "📋 <b>Chọn nhiệm vụ:</b>\n\n"
    rows = []
    for o in offers:
        text += f"{o['title']} — +{o['reward']} tokens\n"
        rows.append([btn(f"{o['title']} (+{o['reward']} 🪙)", url=cpa_service.format_offer_link(o, uid))])
    rows.append([btn("✅ Đã xong", callback_data="verify_video")])
    rows.append([btn("◀️ Quay lại", callback_data="tasks_menu")])
    await tg_api_async("editMessageText", {
        "chat_id": chat, "message_id": mid,
        "text": text, "parse_mode": "HTML", "reply_markup": kb(rows),
    })


async def do_task_referral(chat, uid, mid, username=""):
    user = db.get_user(uid)
    bot_name = os.getenv("BOT_USERNAME", username or "RealEmail_Bot")
    ref = f"https://t.me/{bot_name}?start={user['referral_code']}"
    c = user["referral_count"]
    text = (
        f"👥 <b>Giới thiệu</b>\n\n🔗 Link:\n<code>{ref}</code>\n\n"
        f"• Bạn: +5 tokens/người\n• Bạn bè: +2 tokens\n\n"
        f"📊 Đã mời: {c} | Kiếm: {c*5} tokens"
    )
    await tg_api_async("editMessageText", {
        "chat_id": chat, "message_id": mid,
        "text": text, "parse_mode": "HTML",
        "reply_markup": kb([
            [btn("📤 Chia sẻ", url=f"https://t.me/share/url?url={ref}&text=TempMail miễn phí!")],
            [btn("◀️", callback_data="tasks_menu")],
        ]),
    })


async def do_premium(chat, mid):
    from bot.messages import PREMIUM_INFO
    await tg_api_async("editMessageText", {
        "chat_id": chat, "message_id": mid,
        "text": PREMIUM_INFO, "parse_mode": "HTML",
        "reply_markup": kb([
            [btn("🥉 1 tháng $4.99", callback_data="buy_1m")],
            [btn("🥈 3 tháng $12.99", callback_data="buy_3m")],
            [btn("🥇 1 năm $39.99", callback_data="buy_1y")],
            [btn("◀️", callback_data="main_menu")],
        ]),
    })


async def do_referral(uid, code, name, chat):
    for rid, rd in db.get_all_users().items():
        if rd.get("referral_code") == code and int(rid) != uid:
            u = db.get_user(uid)
            if not u.get("referred_by"):
                db.update_user(uid, referred_by=int(rid))
                db.add_tokens(int(rid), 5, "ref")
                db.add_tokens(uid, 2, "ref")
                db.update_user(int(rid), referral_count=rd.get("referral_count", 0) + 1)
                await tg_api_async("sendMessage", {
                    "chat_id": int(rid),
                    "text": f"🎉 {name} đã dùng link của bạn! +5 tokens!",
                })
            break


# ════════════════════════════════════════════════════════════════
#                     WEBHOOK + HTTP ENDPOINTS
# ════════════════════════════════════════════════════════════════

async def handle_ad_reward(chat, uid, ad_token):
    """Process ad reward after Web App callback"""
    today = time.strftime("%Y-%m-%d")
    if ad_watched_last_reset.get(uid) != today:
        ad_watched_today[uid] = 0
        ad_watched_last_reset[uid] = today
    
    watched = ad_watched_today.get(uid, 0)
    if watched >= AD_MAX_REWARDED_PER_DAY:
        await tg_api_async("sendMessage", {
            "chat_id": chat,
            "text": f"❌ Đã đạt giới hạn {AD_MAX_REWARDED_PER_DAY} video/ngày!",
            "parse_mode": "HTML",
        })
        return
    
    # Verify token and grant reward
    ad_watched_today[uid] = watched + 1
    db.add_tokens(uid, AD_REWARDED_TOKENS, "monetag_reward")
    user = db.get_user(uid)
    
    await tg_api_async("sendMessage", {
        "chat_id": chat,
        "text": (
            f"🎉 <b>+{AD_REWARDED_TOKENS} Tokens!</b>\n\n"
            f"💎 Tokens hiện tại: {user['tokens']}\n"
            f"📊 Video hôm nay: {watched + 1}/{AD_MAX_REWARDED_PER_DAY}"
        ),
        "parse_mode": "HTML",
        "reply_markup": kb([
            [btn("📺 Xem thêm", callback_data="task_video")],
            [btn("📧 Tạo Email", callback_data="create_email")],
            [btn("🏠 Menu", callback_data="main_menu")],
        ]),
    })


WATCH_AD_HTML = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Watch Ad - Earn Tokens</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
        }
        .container { text-align: center; padding: 30px; max-width: 400px; }
        .icon { font-size: 64px; margin-bottom: 16px; }
        h1 { font-size: 24px; margin-bottom: 8px; }
        p { opacity: 0.9; margin-bottom: 24px; }
        .btn-watch {
            background: #fbbf24; color: #1e293b; border: none;
            padding: 16px 40px; border-radius: 14px; font-size: 18px;
            font-weight: 700; cursor: pointer; margin-top: 12px;
            box-shadow: 0 4px 15px rgba(251,191,36,0.4);
        }
        .btn-watch:active { transform: scale(0.96); }
        .status {
            background: rgba(255,255,255,0.2); border-radius: 12px;
            padding: 16px; margin-top: 20px; display: none;
        }
        .timer { font-size: 48px; font-weight: 700; }
        .progress-bar {
            width: 100%; height: 8px; background: rgba(255,255,255,0.3);
            border-radius: 4px; overflow: hidden; margin-top: 12px;
        }
        .progress-fill {
            height: 100%; background: #fbbf24; border-radius: 4px;
            transition: width 1s linear; width: 0%;
        }
        .success { display: none; }
        .success .icon { font-size: 80px; }
        .btn-close {
            background: white; color: #667eea; border: none;
            padding: 14px 32px; border-radius: 12px; font-size: 16px;
            font-weight: 600; cursor: pointer; margin-top: 16px;
        }
        .loading { font-size: 14px; opacity: 0.7; }
    </style>
</head>
<body>
    <!-- Monetag SDK — must be below <body> per docs -->
    <script src='//libtl.com/sdk.js' data-zone='11208686' data-sdk='show_11208686'></script>
    <div class="container">
        <!-- Step 1: User clicks to start -->
        <div id="ad-start">
            <div class="icon">🎁</div>
            <h1>Nhận thưởng!</h1>
            <p>Xem quảng cáo ngắn để nhận <b>+REWARD_TOKENS tokens</b></p>
            <button class="btn-watch" onclick="startAd()">▶️ Bắt đầu xem</button>
        </div>
        <!-- Step 2: Watching ad -->
        <div id="ad-watching" style="display:none;">
            <div class="icon">📺</div>
            <h1>Đang xem quảng cáo...</h1>
            <p>Đợi广告 hoàn thành để nhận thưởng</p>
            <div class="status" id="ad-status" style="display:block;">
                <div class="timer" id="timer">30</div>
                <div class="loading">giây còn lại</div>
                <div class="progress-bar">
                    <div class="progress-fill" id="progress"></div>
                </div>
            </div>
        </div>
        <!-- Step 3: Success -->
        <div class="success" id="ad-success">
            <div class="icon">🎉</div>
            <h1>Hoàn thành!</h1>
            <p id="reward-text">+REWARD_TOKENS tokens đã được thêm</p>
            <button class="btn-close" onclick="closeApp()">✅ Đóng & Nhận thưởng</button>
        </div>
    </div>
    <script>
        const tg = window.Telegram.WebApp;
        tg.expand();
        tg.ready();
        const REWARD_TOKENS = REWARD_TOKENS_PLACEHOLDER;
        const USER_ID = USER_ID_PLACEHOLDER;
        const AD_TOKEN = 'ad_' + USER_ID + '_' + Date.now();
        let adCompleted = false;
        let countdownTimer = null;

        function closeApp() {
            if (adCompleted && tg.initData) {
                tg.sendData(JSON.stringify({
                    action: 'ad_completed',
                    token: AD_TOKEN,
                    uid: USER_ID,
                    reward: REWARD_TOKENS
                }));
            }
            setTimeout(() => tg.close(), 200);
        }

        function showSuccess() {
            adCompleted = true;
            if (countdownTimer) clearInterval(countdownTimer);
            document.getElementById('ad-watching').style.display = 'none';
            document.getElementById('ad-start').style.display = 'none';
            document.getElementById('ad-success').style.display = 'block';
        }

        function startFallbackCountdown() {
            let remaining = 30;
            document.getElementById('ad-watching').style.display = 'block';
            document.getElementById('ad-start').style.display = 'none';
            countdownTimer = setInterval(() => {
                remaining--;
                document.getElementById('timer').textContent = remaining;
                document.getElementById('progress').style.width = ((30 - remaining) / 30 * 100) + '%';
                if (remaining <= 0) {
                    clearInterval(countdownTimer);
                    if (!adCompleted) showSuccess();
                }
            }, 1000);
        }

        // Called when user clicks "Bắt đầu xem" — triggers Monetag Rewarded Interstitial
        function startAd() {
            // Hide start button, show watching UI
            document.getElementById('ad-start').style.display = 'none';
            startFallbackCountdown();

            // Call Monetag SDK (must be from user click)
            if (typeof show_11208686 === 'function') {
                show_11208686().then(() => {
                    console.log('[AD] Rewarded Interstitial completed');
                    showSuccess();
                }).catch(e => {
                    console.warn('[AD] Rewarded Interstitial error:', e);
                    // Still allow reward — ad may have been partially shown
                    if (!adCompleted) showSuccess();
                });
            } else {
                console.warn('[AD] Monetag SDK not loaded yet, retrying...');
                setTimeout(() => {
                    if (typeof show_11208686 === 'function') {
                        show_11208686().then(() => {
                            showSuccess();
                        }).catch(() => {
                            if (!adCompleted) showSuccess();
                        });
                    } else {
                        // SDK never loaded — fallback timer already running
                        console.warn('[AD] SDK unavailable, using fallback timer');
                    }
                }, 2000);
            }
        }
    </script>
</body>
</html>'''

async def handle_webhook(request: web.Request):
    """Receive Telegram webhook update."""
    try:
        update = await request.json()
        asyncio.create_task(process_update(update))
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return web.json_response({"ok": True})


async def handle_health(request: web.Request):
    return web.json_response({
        "status": "running",
        "bot": "TempMail Pro",
        "mode": "async",
    })


async def handle_debug(request: web.Request):
    return web.json_response({
        "bot_token_set": bool(BOT_TOKEN),
        "worker_url_set": bool(WORKER_URL),
        "webhook_url": WEBHOOK_URL or "(not set)",
        "client_type": email_service.client_type,
    })


async def handle_api_create(request: web.Request):
    try:
        email = await asyncio.to_thread(email_service.create_email)
        cache.set(f"email:{email.address}", email, 3600)
        return web.json_response({
            "success": True,
            "email": {"address": email.address, "timestamp": email.timestamp, "key": email.key},
        })
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_api_inbox(request: web.Request):
    addr = request.match_info["addr"]
    try:
        cached = cache.get(f"email:{addr}")
        email_obj = cached if cached else TempEmail(address=addr)
        payload, messages = await asyncio.to_thread(email_service.get_inbox, email_obj)
        if payload:
            cache.set(f"payload:{addr}", payload, 300)
        return web.json_response({
            "success": True,
            "payload": payload,
            "messages": [
                {"mid": m.mid, "subject": m.subject, "sender": m.sender, "date": m.date, "snippet": m.snippet}
                for m in messages
            ],
            "count": len(messages),
        })
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_set_webhook(request: web.Request):
    url = request.query.get("url") or WEBHOOK_URL
    if not url:
        url = f"https://hungba23213213-tempmail-bot.hf.space/webhook/{BOT_TOKEN}"
    webhook_url = f"{url}/webhook/{BOT_TOKEN}" if "/webhook/" not in url else url
    result = await tg_api_async("setWebhook", {
        "url": webhook_url,
        "allowed_updates": json.dumps(["message", "callback_query"]),
    }, timeout=60)
    return web.json_response(result)


async def handle_watch_ad(request: web.Request):
    """Serve the Monetag ad page for Telegram Web App"""
    uid = request.query.get("uid", "0")
    
    # Replace placeholders in HTML
    html = WATCH_AD_HTML.replace("REWARD_TOKENS_PLACEHOLDER", str(AD_REWARDED_TOKENS))
    html = html.replace("USER_ID_PLACEHOLDER", str(uid))
    html = html.replace("REWARD_TOKENS", str(AD_REWARDED_TOKENS))  # For JS const
    
    return web.Response(text=html, content_type="text/html")


async def handle_ad_api_callback(request: web.Request):
    """API endpoint for ad completion callback (alternative to WebApp data)"""
    try:
        data = await request.json()
        uid = data.get("uid")
        ad_token = data.get("token", "")
        
        if not uid:
            return web.json_response({"success": False, "error": "Missing uid"}, status=400)
        
        uid = int(uid)
        today = time.strftime("%Y-%m-%d")
        if ad_watched_last_reset.get(uid) != today:
            ad_watched_today[uid] = 0
            ad_watched_last_reset[uid] = today
        
        watched = ad_watched_today.get(uid, 0)
        if watched >= AD_MAX_REWARDED_PER_DAY:
            return web.json_response({
                "success": False,
                "error": f"Daily limit reached ({AD_MAX_REWARDED_PER_DAY})"
            }, status=429)
        
        # Grant tokens
        ad_watched_today[uid] = watched + 1
        db.add_tokens(uid, AD_REWARDED_TOKENS, "monetag_api_callback")
        user = db.get_user(uid)
        
        return web.json_response({
            "success": True,
            "tokens_added": AD_REWARDED_TOKENS,
            "total_tokens": user["tokens"],
            "watched_today": watched + 1,
            "max_daily": AD_MAX_REWARDED_PER_DAY,
        })
    except Exception as e:
        logger.error(f"Ad callback error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


# ════════════════════════════════════════════════════════════════
#                             MAIN
# ════════════════════════════════════════════════════════════════

async def periodic_save():
    """Save database every 30 seconds."""
    while True:
        await asyncio.sleep(30)
        db.save()


async def auto_set_webhook():
    """Auto-set webhook on startup."""
    if not BOT_TOKEN:
        return
    url = WEBHOOK_URL or f"https://hungba23213213-tempmail-bot.hf.space/webhook/{BOT_TOKEN}"
    if "/webhook/" not in url:
        url = f"{url}/webhook/{BOT_TOKEN}"
    logger.info(f"🔗 Setting webhook: {url}")
    await asyncio.sleep(3)
    for attempt in range(3):
        try:
            result = await tg_api_async("setWebhook", {
                "url": url,
                "allowed_updates": json.dumps(["message", "callback_query"]),
            }, timeout=60)
            if result.get("ok"):
                logger.info("✅ Webhook set successfully!")
                return
            logger.warning(f"Webhook attempt {attempt+1} failed: {result}")
        except Exception as e:
            logger.warning(f"Webhook attempt {attempt+1} error: {e}")
        await asyncio.sleep(10)
    logger.error("❌ Failed to set webhook after 3 attempts")


async def main():
    # Setup web server
    app = web.Application()
    app.router.add_post(f"/webhook/{BOT_TOKEN}", handle_webhook)
    app.router.add_get("/", handle_watch_ad)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/debug", handle_debug)
    app.router.add_post("/api/create", handle_api_create)
    app.router.add_get("/api/inbox/{addr}", handle_api_inbox)
    app.router.add_get("/api/set-webhook", handle_set_webhook)
    app.router.add_post("/api/set-webhook", handle_set_webhook)
    # Monetag ad routes
    app.router.add_get("/watch-ad", handle_watch_ad)
    app.router.add_post("/api/ad-callback", handle_ad_api_callback)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"🚀 Web server started on port {PORT}")

    # Start background tasks
    asyncio.create_task(periodic_save())
    asyncio.create_task(auto_set_webhook())

    # Keep running
    try:
        await asyncio.Event().wait()
    finally:
        db.save()


if __name__ == "__main__":
    asyncio.run(main())
