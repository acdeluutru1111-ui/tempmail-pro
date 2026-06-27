# bot/messages.py — HTML parse mode (reliable, no escape issues)

WELCOME_FIRST = (
    "👋 <b>Chào mừng đến với RealGmailBot!</b>\n"
    "\n"
    "🎁 Bạn nhận được <b>3 tokens</b> miễn phí!"
)

MENU_MESSAGE = (
    "<b>Cách dùng:</b>\n"
    "• 1 token = 1 email tạm thời\n"
    "• Email tồn tại 30 phút\n"
    "• Kiểm tra inbox tự động\n"
    "\n"
    "Bạn đang có: <b>{tokens} tokens</b>\n"
    "\n"
    "🎁 <b>Đăng nhập mỗi ngày để nhận 3 token free!</b>\n"
    "\n"
    "👇 Chọn chức năng bên dưới:"
)

NO_TOKENS_MESSAGE = (
    "❌ <b>Bạn hết tokens rồi!</b>\n"
    "\n"
    "💡 <b>Kiếm tokens miễn phí:</b>\n"
    "\n"
    "1️⃣ Xem video ngắn (30s) → +2 tokens\n"
    "2️⃣ Làm nhiệm vụ đơn giản → +1-5 tokens\n"
    "3️⃣ Mời bạn bè → +5 tokens mỗi người\n"
    "4️⃣ Chơi game may mắn → +1-10 tokens\n"
    "\n"
    "👑 Hoặc nâng cấp Premium:\n"
    "• Unlimited emails\n"
    "• Không cần tokens\n"
    "• Ưu tiên xử lý"
)

TASKS_MENU = (
    "🎯 <b>Nhiệm vụ kiếm tokens</b>\n"
    "\n"
    "📺 <b>Xem Video</b> (+2 tokens)\n"
    "   → Chỉ 30 giây, dễ nhất\n"
    "\n"
    "🎮 <b>Chơi Game</b> (+1-10 tokens)\n"
    "   → May mắn nhận thưởng\n"
    "\n"
    "📋 <b>Làm Offers</b> (+5-20 tokens)\n"
    "   → Cài app, đăng ký...\n"
    "\n"
    "👥 <b>Mời Bạn Bè</b> (+5 tokens/người)\n"
    "   → Chia sẻ link ref\n"
    "\n"
    "💎 Tokens hiện tại: {tokens}"
)

PREMIUM_INFO = (
    "👑 <b>Premium Membership</b>\n"
    "\n"
    "<b>Lợi ích:</b>\n"
    "✅ Unlimited emails (không giới hạn)\n"
    "✅ Không cần tokens\n"
    "✅ Email tồn tại 24 giờ (thay vì 1 giờ)\n"
    "✅ Ưu tiên xử lý\n"
    "✅ Không quảng cáo\n"
    "\n"
    "<b>Gói Premium:</b>\n"
    "🥉 1 tháng - $4.99\n"
    "🥈 3 tháng - $12.99 (tiết kiệm 13%)\n"
    "🥇 1 năm - $39.99 (tiết kiệm 33%)\n"
    "\n"
    "💳 Thanh toán qua Telegram Payments (an toàn)"
)

MY_TOKENS_MSG = (
    "💎 <b>Tài khoản của bạn</b>\n"
    "\n"
    "Status: {status}\n"
    "Tokens: {tokens}\n"
    "Tổng kiếm: {total_earned}\n"
    "Email đã tạo: {emails_created}\n"
    "Đã mời: {referral_count} người"
)

REFERRAL_INFO = (
    "👥 <b>Chương trình Giới thiệu</b>\n"
    "\n"
    "🔗 Link của bạn:\n"
    "<code>{ref_link}</code>\n"
    "\n"
    "<b>Phần thưởng:</b>\n"
    "• Bạn nhận: <b>+5 tokens</b> mỗi người\n"
    "• Bạn bè nhận: <b>+2 tokens</b> khi đăng ký\n"
    "\n"
    "📊 <b>Thống kê:</b>\n"
    "Đã mời: {count} người\n"
    "Kiếm được: {earned} tokens\n"
    "\n"
    "💡 Mẹo: Share vào group, forum để kiếm nhiều hơn!"
)

EMAIL_LIST_HEADER = (
    "📧 <b>Email đã tạo</b>\n"
    "\n"
    "Bạn có <b>{count}</b> email:\n"
)

EMAIL_ITEM_ACTIVE = (
    "✅ <code>{address}</code>\n"
    "   ⏰ Còn {remaining} phút\n"
)

EMAIL_ITEM_EXPIRED = (
    "⏰ <code>{address}</code>\n"
    "   ❌ Đã hết hạn (cần xem ads)\n"
)

AD_REQUIRED_MSG = (
    "⏰ <b>Email này đã hết hạn 5 phút!</b>\n"
    "\n"
    "📺 Xem video 30s để kích hoạt lại email:\n"
    "<code>{address}</code>\n"
    "\n"
    "Sau khi xem, bạn có thể dùng lại email này."
)
