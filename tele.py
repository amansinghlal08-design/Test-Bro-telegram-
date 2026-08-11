#!/usr/bin/env python3
"""
Professional Exam Practice Bot - Render 24/7 Deployment Edition
Language: English
"""

import asyncio
import base64
import json
import logging
import os
import threading
import zlib
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
    BotCommand,
    MenuButtonWebApp
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

# ================== CONFIGURATION ==================
# अपना बॉट टोकन, एडमिन आईडी और मिनी ऐप लिंक यहाँ डालें:
BOT_TOKEN = os.getenv("BOT_TOKEN", "8983460519:AAGGOuXtOsPktEvtkWWT1LKpovNox5R73Hk")
ADMIN_ID = int(os.getenv("ADMIN_ID", "1429768597"))
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://mocktest-pro-lknw.onrender.com/")

# Render Web Service Port (Render ऑटोमैटिकली PORT एनवायरनमेंट प्रोवाइड करता है)
PORT = int(os.getenv("PORT", 8080))
DB_FILE = "bot_database.json"
# ===================================================

# Logging Configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ================== RENDER DUMMY WEB SERVER ==================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot Server is Live 24/7!")

    def log_message(self, format, *args):
        return  # कंसोल साफ रखने के लिए साइलेंट लॉग


def start_health_check_server():
    """Starts background HTTP server for Render port binding & UptimeRobot pings."""
    server = HTTPServer(("0.0.0.0", PORT), HealthCheckHandler)
    logger.info(f"Health-Check HTTP server running on port {PORT}")
    server.serve_forever()


# ================== ENCRYPTED T&C STORAGE ==================
ENCODED_TC_PAYLOAD = (
    "eJytVs1u2zYQvvMpeLCHWnKcxj/QYwEa5NChKVAgaVukOQj0sLW1RZEqQ8pu0AffpE+X1iP11b"
    "Q43k2QBEiLHHZ35/v4mdm93d258b3c9yDffDq5f5Bv7uzXfDqFmZpY7f3+9v1s6vd4P764+HR7"
    "479hLz6dnf95dvb+dH97d2Z3fv9h9v587/Z676sff3a/8v7080+zh6e3l8+d4tYv7vXWz+4/7z"
    "28vv/47rN1P+9v9ePnD0f3u/4b99V/fn319a/e3Z7d99M79+n+4c5v3988nN7tz88f/Xv4/e5D"
    "1719s/P7j3vvL29++uU+vN/7w737+PHN9598O/v64+m/u6O7v3z85t7uT148vLm1y59/mN/t3W"
    "1d171t89n5o/d3f7z9+Ob0bv/v7vV3d/91//u1y/f/6b/s7e/vH331h3/+c3L64+l3x3e37rZt"
    "9+bT/b07vn/f7u3e7V/u/uXev369f7j3v/3T/e1h7Xv3t39+9/4/51d/e/j0e3z/dPf5v/fv7j"
    "9/9/b8f9/9w336uL/3j8e/fLj/s9u7+727vf786fX33+72/y49XNz7y9v7u9Pfnv7j+f2N/05/"
    "fPX+0/F3v/v2v/3Pz16evn17f+6/vPj049Pz6y8v/2f2+tPPz+2N7/413h/6290/vnq1/93b3z"
    "5/fnb91cfT22ff3/z08f31X96cnd68+fT7+4fTr18/e/78X0/vPj1/9m42++7T2fl9369/3p/f"
    "/frX392evj6b/fn05d3x6enr2e3Npz//68en919Pvv3m6f78fG92f/+z//Ld+fPz736ffft6dr"
    "73j37u/ePr85e3Zz//+eL09Pj8/Pj77+5vff37f/h/u7f3v3j+zff//vKnl7e/v/1l9+b47u39"
    "h3vnf3q4/9e7+/tvPj19dnzzxau7d0/vbh/8/7l/evPpxfnZ2en5p7NXX3/y9evnr//207Ozly"
    "9f3H46ffmP2b1fffrx9ePfn7y//9d3P//0/un1q4+nf3P751/M7q+//PLVp49nd2fnX//0dPfF"
    "2fnd+aen7+7efPnF+9sffvn94fdf37z++P7q/W/++NPT12ff/Pn8z2f3H56/fvfl7+affnH//u"
    "vP7/99d/j4+un+0/v7r3979vvj+69f7/78n3+7uf72/P2vv3316fefPz0+3j88/PTl+P7x9dPf"
    "nz8//98="
)

def get_decrypted_terms() -> str:
    try:
        return zlib.decompress(base64.b64decode(ENCODED_TC_PAYLOAD)).decode('utf-8')
    except Exception:
        return (
            "📜 *Terms and Conditions (User Agreement)*\n\n"
            "• *Educational Purpose:* Developed strictly for mock test and self-study practice.\n"
            "• *Disclaimer:* The creator holds no liability for test score errors or technical glitches.\n"
            "• *Conduct:* Spamming or automated exploitation will lead to an immediate ban."
        )


# ================== DATABASE MANAGEMENT ==================
def load_db() -> dict:
    default_structure = {"users": {}, "banned_users": {}, "maintenance": False}
    if not os.path.exists(DB_FILE):
        return default_structure
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error reading database: {e}")
        return default_structure


def save_db(data: dict):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving database: {e}")


def register_or_update_user(user) -> bool:
    db = load_db()
    uid = str(user.id)
    is_new = uid not in db["users"]
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if is_new:
        db["users"][uid] = {
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "username": user.username or "",
            "joined_at": current_time,
            "last_active": current_time
        }
    else:
        db["users"][uid]["first_name"] = user.first_name or ""
        db["users"][uid]["last_name"] = user.last_name or ""
        db["users"][uid]["username"] = user.username or ""
        db["users"][uid]["last_active"] = current_time

    save_db(db)
    return is_new


def is_banned(user_id: int) -> bool:
    db = load_db()
    return str(user_id) in db.get("banned_users", {})


# ================== UI BUILDERS ==================
def get_welcome_text(user_name: str) -> str:
    return (
        f"👋 **Hey {user_name}!** Welcome to **ExamPrep Arena** 🚀\n\n"
        f"⚡ *Your Ultimate Destination for Smart Practice & High-Score Prep!*\n\n"
        f"🔥 **What's in store for you?**\n"
        f"• 🎯 **Exam-Level Mock Tests** — Real questions & pattern drills\n"
        f"• ⚡ **Instant Accuracy & Stats** — Track your strength & speed\n"
        f"• ⏱️ **Timed Challenges** — Master rapid-fire question solving\n"
        f"• 🏆 **Rank Booster** — Polish key concepts & stay ahead\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 **Ready to test your knowledge? Tap below to jump in!**"
    )


def get_welcome_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="🚀 𝗦𝘁𝗮𝗿𝘁 𝗧𝗲𝘀𝘁 𝗣𝗿𝗮𝗰𝘁𝗶𝗰𝗲 (𝗢𝗽𝗲𝗻 𝗔𝗽𝗽)",
                web_app=WebAppInfo(url=MINI_APP_URL)
            )
        ],
        [
            InlineKeyboardButton(
                text="📜 Terms & Guidelines",
                callback_data="view_terms"
            )
        ]
    ])


# ================== BOT STARTUP COMMAND SETUP ==================
async def post_init_setup(application: Application):
    commands = [
        BotCommand("start", "Launch bot & start test practice"),
        BotCommand("test", "Directly launch Mini App arena"),
        BotCommand("terms", "View Terms & Guidelines")
    ]
    await application.bot.set_my_commands(commands)

    # Left-side chat bar WebApp Menu Button
    menu_btn = MenuButtonWebApp(
        text="🚀 Open Arena",
        web_app=WebAppInfo(url=MINI_APP_URL)
    )
    await application.bot.set_chat_menu_button(menu_button=menu_btn)
    logger.info("Bot commands and WebApp menu button configured.")


# ================== USER HANDLERS ==================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = load_db()

    if is_banned(user.id):
        await update.message.reply_text("🚫 **Access Denied:** You have been banned from using this bot.")
        return

    is_new = register_or_update_user(user)

    if is_new and user.id != ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"🔔 <b>New Aspirant Joined!</b>\n"
                    f"👤 <b>Name:</b> {user.first_name}\n"
                    f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
                    f"🔗 <b>Username:</b> @{user.username or 'N/A'}"
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass

    if db.get("maintenance", False) and user.id != ADMIN_ID:
        await update.message.reply_text(
            "🛠️ **Maintenance in Progress**\n\n"
            "We are currently rolling out new test sets. Please check back shortly!",
            parse_mode="Markdown"
        )
        return

    user_name = user.first_name if user.first_name else "Aspirant"
    await update.message.reply_text(
        text=get_welcome_text(user_name),
        reply_markup=get_welcome_markup(),
        parse_mode="Markdown"
    )


async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("🚫 **Access Denied:** You have been banned.")
        return

    keyboard = [
        [
            InlineKeyboardButton(
                text="🚀 Launch Test Arena",
                web_app=WebAppInfo(url=MINI_APP_URL)
            )
        ]
    ]
    await update.message.reply_text(
        "📝 **Click below to launch your practice session:**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def terms_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    terms_text = get_decrypted_terms()
    keyboard = [[InlineKeyboardButton("🔙 Back to Arena", callback_data="back_to_welcome")]]
    await update.message.reply_text(
        text=terms_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# ================== CALLBACK HANDLER (IN-APP T&C) ==================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user

    if data == "view_terms":
        terms_text = get_decrypted_terms()
        keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_welcome")]]
        await query.edit_message_text(
            text=terms_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif data == "back_to_welcome":
        user_name = user.first_name if user.first_name else "Aspirant"
        await query.edit_message_text(
            text=get_welcome_text(user_name),
            reply_markup=get_welcome_markup(),
            parse_mode="Markdown"
        )


# ================== ADMIN HANDLERS ==================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    panel_text = (
        "👑 **ADMIN CONTROL PANEL**\n\n"
        "📊 **Analytics & Info:**\n"
        "• `/stats` — View total users and active metrics.\n"
        "• `/user <user_id>` — Look up full profile info.\n\n"
        "📢 **Messaging:**\n"
        "• `/broadcast <message>` — Send clean, direct broadcast.\n"
        "• `/dm <user_id> <message>` — Send direct message to a user.\n\n"
        "🛡️ **Moderation & System:**\n"
        "• `/ban <user_id> [reason]` — Ban a user.\n"
        "• `/unban <user_id>` — Unban a user.\n"
        "• `/banned` — List all banned users.\n"
        "• `/maintenance on/off` — Toggle maintenance mode."
    )
    await update.message.reply_text(panel_text, parse_mode="Markdown")


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    db = load_db()
    users = db.get("users", {})
    banned = db.get("banned_users", {})
    m_status = "🔴 ON" if db.get("maintenance") else "🟢 OFF"

    stats_msg = (
        f"📊 **BOT STATISTICS**\n\n"
        f"👥 **Total Registered Users:** `{len(users)}`\n"
        f"🚫 **Banned Users:** `{len(banned)}`\n"
        f"🛠️ **Maintenance Mode:** {m_status}\n\n"
        f"📋 **Last 5 Active / Joined Users:**\n"
    )

    recent_users = list(users.items())[-5:]
    for uid, uinfo in reversed(recent_users):
        u_name = uinfo.get("first_name", "Unknown")
        u_handle = f"@{uinfo.get('username')}" if uinfo.get("username") else "No Handle"
        last_seen = uinfo.get("last_active", uinfo.get("joined_at", "N/A"))
        stats_msg += f"• `{uid}` | {u_name} ({u_handle}) | 🕒 `{last_seen}`\n"

    await update.message.reply_text(stats_msg, parse_mode="Markdown")


async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ **Usage:** `/broadcast <message>`\n\n"
            "Example:\n`/broadcast New mock test series is now live!`",
            parse_mode="Markdown"
        )
        return

    broadcast_msg = update.message.text.split(None, 1)[1]
    db = load_db()
    users = db.get("users", {})

    status_msg = await update.message.reply_text(
        f"⏳ **Broadcasting started...**\nTarget Users: `{len(users)}`",
        parse_mode="Markdown"
    )

    success, blocked, failed = 0, 0, 0

    for uid in users.keys():
        try:
            await context.bot.send_message(
                chat_id=int(uid),
                text=broadcast_msg,
                parse_mode="Markdown"
            )
            success += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            err_str = str(e).lower()
            if "blocked" in err_str or "chat not found" in err_str or "user is deactivated" in err_str:
                blocked += 1
            else:
                failed += 1

    summary = (
        f"✅ **Broadcast Completed!**\n\n"
        f"🟢 **Delivered:** `{success}`\n"
        f"🚫 **Blocked/Inactive:** `{blocked}`\n"
        f"❌ **Failed:** `{failed}`\n"
        f"📊 **Total Targets:** `{len(users)}`"
    )
    await status_msg.edit_text(summary, parse_mode="Markdown")


async def admin_dm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ **Usage:** `/dm <user_id> <message>`\n\n"
            "Example:\n`/dm 123456789 Hello, your test score has been updated.`",
            parse_mode="Markdown"
        )
        return

    target_uid = context.args[0]
    dm_text = update.message.text.split(None, 2)[2]

    try:
        await context.bot.send_message(
            chat_id=int(target_uid),
            text=dm_text,
            parse_mode="Markdown"
        )
        await update.message.reply_text(f"✅ Message sent to `{target_uid}`.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to send DM: `{e}`", parse_mode="Markdown")


async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("⚠️ **Usage:** `/ban <user_id> [reason]`", parse_mode="Markdown")
        return

    target_uid = context.args[0]
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "Violation of terms"

    if target_uid == str(ADMIN_ID):
        await update.message.reply_text("❌ You cannot ban the Admin account!")
        return

    db = load_db()
    db["banned_users"][target_uid] = {
        "reason": reason,
        "banned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_db(db)
    await update.message.reply_text(f"🚫 **User Banned:** `{target_uid}`\n📝 **Reason:** {reason}", parse_mode="Markdown")


async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("⚠️ **Usage:** `/unban <user_id>`", parse_mode="Markdown")
        return

    target_uid = context.args[0]
    db = load_db()

    if target_uid in db.get("banned_users", {}):
        del db["banned_users"][target_uid]
        save_db(db)
        await update.message.reply_text(f"✅ User `{target_uid}` unbanned.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"ℹ️ User `{target_uid}` is not in the ban list.")


async def admin_banned_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    db = load_db()
    banned = db.get("banned_users", {})

    if not banned:
        await update.message.reply_text("🟢 There are currently no banned users.")
        return

    banned_text = f"🚫 **BANNED USERS ({len(banned)}):**\n\n"
    for uid, info in banned.items():
        banned_text += f"• `{uid}` | Reason: {info.get('reason')} | 🕒 `{info.get('banned_at')}`\n"

    await update.message.reply_text(banned_text, parse_mode="Markdown")


async def admin_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("⚠️ **Usage:** `/user <user_id>`", parse_mode="Markdown")
        return

    target_uid = context.args[0]
    db = load_db()
    user_data = db.get("users", {}).get(target_uid)

    if not user_data:
        await update.message.reply_text(f"❌ User `{target_uid}` not found.", parse_mode="Markdown")
        return

    is_user_banned = "🔴 YES" if target_uid in db.get("banned_users", {}) else "🟢 NO"

    info_text = (
        f"👤 **USER DETAILS:**\n\n"
        f"🆔 **ID:** `{target_uid}`\n"
        f"📛 **First Name:** {user_data.get('first_name', 'N/A')}\n"
        f"📛 **Last Name:** {user_data.get('last_name', 'N/A')}\n"
        f"🔗 **Username:** @{user_data.get('username') or 'N/A'}\n"
        f"📅 **Joined Date:** `{user_data.get('joined_at', 'N/A')}`\n"
        f"🕒 **Last Active:** `{user_data.get('last_active', 'N/A')}`\n"
        f"🚫 **Banned:** {is_user_banned}"
    )
    await update.message.reply_text(info_text, parse_mode="Markdown")


async def admin_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args or context.args[0].lower() not in ["on", "off"]:
        await update.message.reply_text("⚠️ **Usage:** `/maintenance on` or `/maintenance off`", parse_mode="Markdown")
        return

    mode = context.args[0].lower() == "on"
    db = load_db()
    db["maintenance"] = mode
    save_db(db)

    status_str = "🔴 **ENABLED (ON)**." if mode else "🟢 **DISABLED (OFF)**."
    await update.message.reply_text(f"🛠️ Maintenance mode is now {status_str}", parse_mode="Markdown")


# ================== MAIN APP RUNNER ==================
def main():
    # 1. Background HTTP Server for Render
    server_thread = threading.Thread(target=start_health_check_server, daemon=True)
    server_thread.start()

    # 2. Telegram Bot Polling Setup
    app = Application.builder().token(BOT_TOKEN).post_init(post_init_setup).build()

    # User Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("test", test_command))
    app.add_handler(CommandHandler("terms", terms_command))

    # In-App Callback Handler
    app.add_handler(CallbackQueryHandler(callback_handler, pattern="^(view_terms|back_to_welcome)$"))

    # Admin Handlers
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(CommandHandler("dm", admin_dm))
    app.add_handler(CommandHandler("ban", admin_ban))
    app.add_handler(CommandHandler("unban", admin_unban))
    app.add_handler(CommandHandler("banned", admin_banned_list))
    app.add_handler(CommandHandler("user", admin_user_info))
    app.add_handler(CommandHandler("maintenance", admin_maintenance))

    print("🤖 Exam Practice Bot is now polling & running on Render...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
