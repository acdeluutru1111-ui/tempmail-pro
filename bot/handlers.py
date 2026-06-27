# bot/handlers.py — HTML parse mode + robust error handling

import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.database import db
from bot.messages import *
from services.email_service import email_service, TempEmail
from utils.cache import cache

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
#                         /start COMMAND
# ════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    try:
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "User"

        # Handle referral
        if context.args:
            ref_code = context.args[0]
            all_users = db.get_all_users()
            for uid, udata in all_users.items():
                if udata.get("referral_code") == ref_code and int(uid) != user_id:
                    user = db.get_user(user_id)
                    if not user.get("referred_by"):
                        db.update_user(user_id, referred_by=int(uid))
                        db.add_tokens(int(uid), 5, "referral_bonus")
                        db.add_tokens(user_id, 2, "joined_via_referral")
                        db.update_user(
                            int(uid),
                            referral_count=udata.get("referral_count", 0) + 1,
                        )
                        try:
                            await context.bot.send_message(
                                int(uid),
                                f"🎉 {user_name} đã dùng link của bạn!\n+5 tokens đã được thêm!",
                            )
                        except Exception:
                            pass
                    break

        user = db.get_user(user_id)

        keyboard = [
            [
                InlineKeyboardButton("📧 Tạo Email", callback_data="create_email"),
                InlineKeyboardButton(
                    f"💎 Tokens: {user['tokens']}", callback_data="my_tokens"
                ),
            ],
            [
                InlineKeyboardButton("🎯 Nhiệm vụ", callback_data="tasks_menu"),
                InlineKeyboardButton("👑 Premium", callback_data="premium"),
            ],
            [
                InlineKeyboardButton(
                    "👥 Mời bạn bè (+5 tokens)", callback_data="task_referral"
                ),
            ],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.message:
            await update.message.reply_text(
                WELCOME_MESSAGE,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        elif update.callback_query:
            await update.callback_query.edit_message_text(
                WELCOME_MESSAGE,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )

    except Exception as e:
        logger.error(f"cmd_start error: {e}", exc_info=True)
        # Fallback: send plain text
        try:
            if update.message:
                await update.message.reply_text("👋 Chào mừng! Gõ /start để bắt đầu.")
            elif update.callback_query:
                await update.callback_query.edit_message_text("👋 Chào mừng! Gõ /start để bắt đầu.")
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════
#                       CALLBACK ROUTER
# ════════════════════════════════════════════════════════════════════

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all callback queries"""
    query = update.callback_query
    await query.answer()

    data = query.data
    logger.info(f"Callback: user={query.from_user.id} data={data}")

    try:
        if data == "main_menu":
            await cmd_start(update, context)
        elif data == "create_email":
            await handle_create_email(update, context)
        elif data == "my_tokens":
            await handle_my_tokens(update, context)
        elif data == "tasks_menu":
            from bot.tasks import show_tasks_menu
            await show_tasks_menu(update, context)
        elif data == "task_video":
            from bot.tasks import task_video
            await task_video(update, context)
        elif data == "task_game":
            from bot.tasks import task_game
            await task_game(update, context)
        elif data == "task_offers":
            from bot.tasks import task_offers
            await task_offers(update, context)
        elif data == "task_referral":
            from bot.tasks import task_referral
            await task_referral(update, context)
        elif data == "verify_video":
            from bot.tasks import verify_video
            await verify_video(update, context)
        elif data == "premium":
            await handle_premium(update, context)
        elif data.startswith("inbox_"):
            email_addr = data[len("inbox_"):]
            await handle_inbox(update, context, email_addr)
        else:
            await query.answer("⚠️ Chức năng đang phát triển", show_alert=True)

    except Exception as e:
        logger.error(f"Callback error: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                f"❌ Lỗi: {str(e)[:200]}\n\nNhấn /start để thử lại.",
            )
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════
#                        CREATE EMAIL
# ════════════════════════════════════════════════════════════════════

async def handle_create_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create temp email"""
    query = update.callback_query
    user_id = query.from_user.id

    # Check tokens
    if not db.use_tokens(user_id):
        keyboard = [
            [InlineKeyboardButton("🎯 Kiếm Tokens", callback_data="tasks_menu")],
            [InlineKeyboardButton("👑 Mua Premium", callback_data="premium")],
        ]
        await query.edit_message_text(
            NO_TOKENS_MESSAGE,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Show loading
    await query.edit_message_text("⏳ Đang tạo email...")

    try:
        email = await asyncio.to_thread(email_service.create_email)
        cache.set(f"email:{email.address}", email, 3600)

        user = db.get_user(user_id)
        db.update_user(user_id, emails_created=user["emails_created"] + 1)
        tokens_left = db.get_user(user_id)["tokens"]

        keyboard = [
            [InlineKeyboardButton("📨 Xem Inbox", callback_data=f"inbox_{email.address}")],
            [InlineKeyboardButton("📧 Tạo Email Mới", callback_data="create_email")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")],
        ]

        msg = (
            f"✅ <b>Email đã tạo thành công!</b>\n\n"
            f"📧 Email của bạn:\n<code>{email.address}</code>\n\n"
            f"⏰ Hiệu lực: 1 giờ\n"
            f"💎 Tokens còn lại: {tokens_left}\n\n"
            f"📨 Nhấn 'Xem Inbox' để kiểm tra email"
        )

        await query.edit_message_text(
            msg,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    except Exception as e:
        logger.error(f"Create email error: {e}", exc_info=True)
        db.add_tokens(user_id, 1, "refund_create_failed")
        await query.edit_message_text(
            f"❌ Lỗi: {str(e)[:200]}\n\nToken đã được hoàn lại.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Thử lại", callback_data="create_email")],
                [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")],
            ]),
        )


# ════════════════════════════════════════════════════════════════════
#                          VIEW INBOX
# ════════════════════════════════════════════════════════════════════

async def handle_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE, email_addr: str):
    """Show inbox for an email"""
    query = update.callback_query
    user_id = query.from_user.id

    await query.edit_message_text("⏳ Đang kiểm tra inbox...")

    try:
        cached_email = cache.get(f"email:{email_addr}")
        email = cached_email if cached_email else TempEmail(address=email_addr)

        payload, messages = await asyncio.to_thread(email_service.get_inbox, email)

        if payload:
            cache.set(f"payload:{email_addr}", payload, 300)

        if not messages:
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh", callback_data=f"inbox_{email_addr}")],
                [InlineKeyboardButton("📧 Tạo Email Mới", callback_data="create_email")],
                [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")],
            ]
            await query.edit_message_text(
                f"📭 <b>Inbox trống</b>\n\n"
                f"<code>{email_addr}</code>\n\n"
                f"Chưa có email nào. Nhấn Refresh để kiểm tra lại.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        # Format messages
        msg_lines = []
        for i, msg in enumerate(messages[:10]):
            subj = msg.subject[:50] if msg.subject else "No Subject"
            sender = msg.sender[:30] if msg.sender else "Unknown"
            msg_lines.append(f"📧 <b>{i+1}.</b> {subj}")
            msg_lines.append(f"   👤 <i>{sender}</i>")
            if msg.snippet:
                msg_lines.append(f"   └ {msg.snippet[:60]}")
            msg_lines.append("")

        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data=f"inbox_{email_addr}")],
            [InlineKeyboardButton("📧 Email Mới", callback_data="create_email")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")],
        ]

        text = (
            f"📬 <b>Inbox</b> - {len(messages)} email(s)\n\n"
            + "\n".join(msg_lines)
            + f"\n📧 <code>{email_addr}</code>"
        )

        await query.edit_message_text(
            text[:4000],
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    except Exception as e:
        logger.error(f"Inbox error: {e}", exc_info=True)
        await query.edit_message_text(
            f"❌ Lỗi kiểm tra inbox: {str(e)[:200]}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Thử lại", callback_data=f"inbox_{email_addr}")],
                [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")],
            ]),
        )


# ════════════════════════════════════════════════════════════════════
#                        MY TOKENS
# ════════════════════════════════════════════════════════════════════

async def handle_my_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user stats"""
    query = update.callback_query
    user_id = query.from_user.id
    user = db.get_user(user_id)

    status = "👑 Premium Active" if db.is_premium(user_id) else "👤 Free User"

    text = MY_TOKENS_MSG.format(
        status=status,
        tokens=user['tokens'],
        total_earned=user['total_earned'],
        emails_created=user['emails_created'],
        referral_count=user['referral_count'],
    )

    keyboard = [
        [InlineKeyboardButton("🎯 Kiếm thêm tokens", callback_data="tasks_menu")],
        [InlineKeyboardButton("👑 Nâng cấp Premium", callback_data="premium")],
        [InlineKeyboardButton("◀️ Menu", callback_data="main_menu")],
    ]

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ════════════════════════════════════════════════════════════════════
#                         PREMIUM
# ════════════════════════════════════════════════════════════════════

async def handle_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show premium options"""
    query = update.callback_query

    keyboard = [
        [InlineKeyboardButton("🥉 1 tháng - $4.99", callback_data="buy_premium_1m")],
        [InlineKeyboardButton("🥈 3 tháng - $12.99", callback_data="buy_premium_3m")],
        [InlineKeyboardButton("🥇 1 năm - $39.99", callback_data="buy_premium_1y")],
        [InlineKeyboardButton("◀️ Quay lại", callback_data="main_menu")],
    ]

    await query.edit_message_text(
        PREMIUM_INFO,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
