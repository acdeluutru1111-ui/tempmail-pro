# bot/tasks.py — HTML parse mode + robust error handling

import random
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.database import db
from services.cpa_service import cpa_service

logger = logging.getLogger(__name__)


async def show_tasks_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hiển thị menu nhiệm vụ"""
    query = update.callback_query
    user_id = query.from_user.id
    user = db.get_user(user_id)

    keyboard = [
        [InlineKeyboardButton("📺 Xem Video (+2 tokens)", callback_data="task_video")],
        [InlineKeyboardButton("🎮 Chơi Game (+1-10 tokens)", callback_data="task_game")],
        [InlineKeyboardButton("📋 Làm Offers (+5-20 tokens)", callback_data="task_offers")],
        [InlineKeyboardButton("👥 Mời Bạn Bè (+5 tokens)", callback_data="task_referral")],
        [InlineKeyboardButton("🏠 Menu Chính", callback_data="main_menu")],
    ]

    from bot.messages import TASKS_MENU
    text = TASKS_MENU.format(tokens=user["tokens"])

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def task_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xem rewarded video"""
    query = update.callback_query

    keyboard = [
        [InlineKeyboardButton("✅ Đã xem xong (+2 tokens)", callback_data="verify_video")],
        [InlineKeyboardButton("◀️ Quay lại", callback_data="tasks_menu")],
    ]

    await query.edit_message_text(
        "📺 <b>Xem video kiếm tokens</b>\n\n"
        "⏱️ Chỉ mất 30 giây\n"
        "🎁 Nhận ngay +2 tokens\n\n"
        "📺 Xem video, sau đó nhấn nút xác nhận!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def verify_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify video watched — award tokens"""
    query = update.callback_query
    user_id = query.from_user.id

    db.add_tokens(user_id, 2, "video_reward")
    user = db.get_user(user_id)

    keyboard = [
        [InlineKeyboardButton("📺 Xem thêm Video", callback_data="task_video")],
        [InlineKeyboardButton("📧 Tạo Email", callback_data="create_email")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")],
    ]

    await query.edit_message_text(
        f"🎉 <b>+2 Tokens đã thêm!</b>\n\n"
        f"💎 Tokens hiện tại: {user['tokens']}\n\n"
        f"📺 Muốn xem thêm video?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def task_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mini game - Spin wheel"""
    query = update.callback_query
    user_id = query.from_user.id

    await query.edit_message_text("🎡 Đang quay...")
    await asyncio.sleep(1.5)

    reward = random.choice([1, 2, 3, 5, 10])
    db.add_tokens(user_id, reward, "spin_wheel")
    user = db.get_user(user_id)

    keyboard = [
        [InlineKeyboardButton("🔄 Quay lại (xem ads)", callback_data="task_video")],
        [InlineKeyboardButton("📧 Tạo Email", callback_data="create_email")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")],
    ]

    await query.edit_message_text(
        f"🎉 <b>Chúc mừng!</b>\n\n"
        f"Bạn nhận được: <b>{reward} tokens</b>\n"
        f"💎 Tổng tokens: {user['tokens']}\n\n"
        f"Muốn quay thêm? Xem video 30s!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def task_offers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hiển thị CPA offers"""
    query = update.callback_query
    user_id = query.from_user.id

    user_lang = query.from_user.language_code or "en"
    geo = "VN" if user_lang == "vi" else "US"

    offers = cpa_service.get_offers(geo)

    if not offers:
        await query.answer("Không có offers cho khu vực của bạn", show_alert=True)
        return

    text = "📋 <b>Chọn nhiệm vụ:</b>\n\n"
    keyboard = []

    for offer in offers:
        reward = offer['reward']
        title = offer['title']
        text += f"{title}\n   └ Thưởng: +{reward} tokens\n\n"
        offer_link = cpa_service.format_offer_link(offer, user_id)
        keyboard.append([
            InlineKeyboardButton(
                f"{title} (+{reward} 🪙)",
                url=offer_link,
            )
        ])

    keyboard.append([
        InlineKeyboardButton("✅ Đã hoàn thành", callback_data="verify_video")
    ])
    keyboard.append([
        InlineKeyboardButton("◀️ Quay lại", callback_data="tasks_menu")
    ])

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def task_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Referral program"""
    query = update.callback_query
    user_id = query.from_user.id
    user = db.get_user(user_id)

    bot_username = context.bot.username or "YourBot"
    ref_code = user["referral_code"]
    ref_link = f"https://t.me/{bot_username}?start={ref_code}"

    count = user["referral_count"]
    earned = count * 5

    from bot.messages import REFERRAL_INFO
    text = REFERRAL_INFO.format(
        ref_link=ref_link,
        count=count,
        earned=earned,
    )

    keyboard = [
        [InlineKeyboardButton(
            "📤 Chia sẻ Link",
            url=f"https://t.me/share/url?url={ref_link}&text=Dùng TempMail miễn phí!",
        )],
        [InlineKeyboardButton("◀️ Quay lại", callback_data="tasks_menu")],
    ]

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
