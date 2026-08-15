#!/usr/bin/env python3
"""
Professional Exam Practice Bot - Render 24/7 Deployment Edition
Fixed: Auto-Healing Database & Fail-Safe User Delivery
"""

import asyncio
import base64
import json
import logging
import os
import threading
import zlib
import html
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
    MessageHandler,
    filters,
    ContextTypes
)

# ================== CONFIGURATION ==================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8983460519:AAGGOuXtOsPktEvtkWWT1LKpovNox5R73Hk")
ADMIN_ID = int(os.getenv("ADMIN_ID", "1429768597"))
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://mocktest-pro-lknw.onrender.com/")

# Render Web Service Port
PORT = int(os.getenv("PORT", 8080))
DB_FILE = os.path.join(os.getcwd(), "bot_database.json")
# ===================================================

# Logging Configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database Lock (To prevent file corruption during multiple simultaneous users)
db_lock = threading.Lock()


# ================== RENDER DUMMY WEB SERVER ==================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot Server is Live 24/7!")
    def log_message(self, format, *args):
        return  # साइलेंट लॉग


def start_health_check_server():
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
        raw_text = zlib.decompress(base64.b64decode(ENCODED_TC_PAYLOAD)).decode('utf-8')
        return raw_text.replace('*', '<b>').replace('</b>\n', '</b>\n')
    except Exception:
        return (
            "📜 <b>Terms and Conditions (User Agreement)</b>\n\n"
            "• <b>Educational Purpose:</b> Developed strictly for mock test and self-study practice.\n"
            "• <b>Disclaimer:</b> The creator holds no liability for test score errors or technical glitches.\n"
            "• <b>Conduct:</b> Spamming or automated exploitation will lead to an immediate ban."
        )


# ================== AUTO-HEALING DATABASE ==================
def load_db() -> dict:
    default_structure = {"users": {}, "banned_users": {}, "maintenance": False}
    if not os.path.exists(DB_FILE):
        return default_structure
    
    with db_lock:
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content: return default_structure
                data = json.loads(content)
                if "users" not in data: data["users"] = {}
                if "banned_users" not in data: data["banned_users"] = {}
                return data
        except Exception as e:
            logger.error(f"CORRUPTED JSON DETECTED. Auto-Healing Database... Error: {e}")
            # अगर फाइल क्रैश है, तो उसे फ्रेश फाइल से रिप्लेस कर दो ताकि बोट काम करना बंद न करे
            try:
                with open(DB_FILE, "w", encoding="utf-8") as f:
                    json.dump(default_structure, f, indent=4)
            except:
                pass
            return default_structure


def save_db(data: dict):
    with db_lock:
        try:
            with open(DB_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving database: {e}")


# ================== UI BUILDERS (HTML SAFE) ==================
def get_welcome_text(user_name: str) -> str:
    safe_name = html.escape(user_name)
    return (
        f"👋 <b>Hey {safe_name}!</b> Welcome to <b>ExamPrep Arena</b> 🚀\n\n"
        f"⚡ <i>Your Ultimate Destination for Smart Practice & High-Score Prep!</i>\n\n"
        f"🔥 <b>What's in store for you?</b>\n"
        f"• 🎯 <b>Exam-Level Mock Tests</b> — Real questions & pattern drills\n"
        f"• ⚡ <b>Instant Accuracy & Stats</b> — Track your strength & speed\n"
        f"• ⏱️ <b>Timed Challenges</b> — Master rapid-fire question solving\n"
        f"• 🏆 <b>Rank Booster</b> — Polish key concepts & stay ahead\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 <b>Ready to test your knowledge? Tap below to jump in!</b>"
    )

def get_welcome_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text="🚀 𝗦𝘁𝗮𝗿𝘁 𝗧𝗲𝘀𝘁 𝗣𝗿𝗮𝗰𝘁𝗶𝗰𝗲 (𝗢𝗽𝗲𝗻 𝗔𝗽𝗽)", web_app=WebAppInfo(url=MINI_APP_URL))],
        [InlineKeyboardButton(text="📜 Terms & Guidelines", callback_data="view_terms")]
    ])


# ================== BOT STARTUP COMMAND SETUP ==================
async def post_init_setup(application: Application):
    commands = [
        BotCommand("start", "Launch bot & start test practice"),
        BotCommand("test", "Directly launch Mini App arena"),
        BotCommand("terms", "View Terms & Guidelines")
    ]
    await application.bot.set_my_commands(commands)
    menu_btn = MenuButtonWebApp(text="🚀 Open Arena", web_app=WebAppInfo(url=MINI_APP_URL))
    await application.bot.set_chat_menu_button(menu_button=menu_btn)
    logger.info("Bot commands and WebApp menu button configured.")


# ================== CORE USER HANDLERS (FAIL-SAFE) ==================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        if not user or not update.message: return

        # 1. Safely load DB
        db = load_db()

        # 2. Ban Check
        uid = str(user.id)
        if uid in db.get("banned_users", {}):
            await update.message.reply_text("🚫 <b>Access Denied:</b> You are banned.", parse_mode="HTML")
            return

        # 3. Registration
        is_new = False
        try:
            if uid not in db.get("users", {}):
                is_new = True
                db["users"][uid] = {
                    "first_name": user.first_name or "",
                    "username": user.username or "",
                    "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                save_db(db)
        except Exception as e:
            logger.error(f"User registration failed, but continuing: {e}")

        # 4. Notify Admin
        if is_new and user.id != ADMIN_ID:
            try:
                safe_fname = html.escape(user.first_name or "N/A")
                safe_uname = html.escape(user.username or "N/A")
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"🔔 <b>New Aspirant!</b>\n👤 Name: {safe_fname}\n🔗 @{safe_uname}",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        # 5. Maintenance Check
        if db.get("maintenance", False) and user.id != ADMIN_ID:
            await update.message.reply_text("🛠️ <b>Maintenance in Progress.</b> Please check back shortly!", parse_mode="HTML")
            return

        # 6. Final Welcome Render
        user_name = user.first_name if user.first_name else "Aspirant"
        await update.message.reply_text(
            text=get_welcome_text(user_name),
            reply_markup=get_welcome_markup(),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"CRITICAL ERROR in start_command: {e}")
        # Absolute Fail-Safe: If everything fails, send simple text
        if update.message:
            await update.message.reply_text("Server is rebooting or busy. Please click /start again.")


async def catch_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggers Welcome Menu if a user types anything else like 'Hi', 'Hello', etc."""
    if update.effective_message and not update.effective_message.text.startswith('/'):
        await start_command(update, context)


async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if is_banned(update.effective_user.id): return
        keyboard = [[InlineKeyboardButton(text="🚀 Launch Test Arena", web_app=WebAppInfo(url=MINI_APP_URL))]]
        await update.message.reply_text("📝 <b>Click below to launch:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Test command error: {e}")


async def terms_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🔙 Back to Arena", callback_data="back_to_welcome")]]
    await update.message.reply_text(text=get_decrypted_terms(), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


# ================== CALLBACK HANDLER ==================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        data = query.data
        user = update.effective_user

        if data == "view_terms":
            keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_welcome")]]
            await query.edit_message_text(text=get_decrypted_terms(), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        elif data == "back_to_welcome":
            user_name = user.first_name if user.first_name else "Aspirant"
            await query.edit_message_text(text=get_welcome_text(user_name), reply_markup=get_welcome_markup(), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Callback error: {e}")


# ================== ADMIN HANDLERS ==================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    panel_text = (
        "👑 <b>ADMIN CONTROL PANEL</b>\n\n"
        "📊 <b>Analytics:</b> <code>/stats</code>, <code>/user &lt;id&gt;</code>\n"
        "📢 <b>Messaging:</b> <code>/broadcast &lt;msg&gt;</code>, <code>/dm &lt;id&gt; &lt;msg&gt;</code>\n"
        "🛡️ <b>Mod:</b> <code>/ban &lt;id&gt;</code>, <code>/unban &lt;id&gt;</code>, <code>/banned</code>\n"
        "🛠️ <b>System:</b> <code>/maintenance on/off</code>"
    )
    await update.message.reply_text(panel_text, parse_mode="HTML")


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    db = load_db()
    users, banned = db.get("users", {}), db.get("banned_users", {})
    m_status = "🔴 ON" if db.get("maintenance") else "🟢 OFF"

    stats_msg = f"📊 <b>BOT STATISTICS</b>\n\n👥 <b>Users:</b> <code>{len(users)}</code>\n🚫 <b>Banned:</b> <code>{len(banned)}</code>\n🛠️ <b>Maintenance:</b> {m_status}\n\n📋 <b>Last 5 Users:</b>\n"
    for uid, uinfo in list(users.items())[-5:][::-1]:
        u_name = html.escape(uinfo.get("first_name", "Unknown"))
        stats_msg += f"• <code>{uid}</code> | {u_name} | 🕒 <code>{uinfo.get('joined_at', 'N/A')}</code>\n"
    await update.message.reply_text(stats_msg, parse_mode="HTML")


async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args: return await update.message.reply_text("⚠️ <b>Usage:</b> <code>/broadcast &lt;msg&gt;</code>", parse_mode="HTML")

    msg = update.message.text.split(None, 1)[1]
    users = load_db().get("users", {})
    status = await update.message.reply_text(f"⏳ <b>Broadcasting to {len(users)} users...</b>", parse_mode="HTML")
    success, blocked = 0, 0

    for uid in users.keys():
        try:
            await context.bot.send_message(chat_id=int(uid), text=msg, parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.05)
        except:
            blocked += 1

    await status.edit_text(f"✅ <b>Broadcast Done!</b>\n🟢 Delivered: {success}\n🚫 Failed/Blocked: {blocked}", parse_mode="HTML")


# GLOBAL ERROR HANDLER
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)


# ================== MAIN APP RUNNER ==================
def main():
    # 1. Background Web Server
    threading.Thread(target=start_health_check_server, daemon=True).start()

    # 2. Telegram Bot
    app = Application.builder().token(BOT_TOKEN).post_init(post_init_setup).build()

    # Core Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("test", test_command))
    app.add_handler(CommandHandler("terms", terms_command))
    app.add_handler(CallbackQueryHandler(callback_handler, pattern="^(view_terms|back_to_welcome)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, catch_all_messages))

    # Admin Handlers
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))

    app.add_error_handler(error_handler)
    print("🤖 Ultra-Resilient Exam Practice Bot is polling on Render...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
