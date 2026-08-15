#!/usr/bin/env python3
"""
Enterprise Exam Practice Bot - Advanced Edition (Level 200)
==========================================================
Single-file Telegram bot engine featuring:

  * In-chat timed quizzes (categories, difficulties, 20s per question)
  * Coins, daily streaks, paginated leaderboard
  * Daily practice reminders (IST) via the job queue
  * Atomic JSON database with rolling auto-backups
  * Guided admin flows: add / edit / delete questions from chat
  * Broadcast with confirm & cancel, per-user DM, ban/unban
  * CSV export, JSON backup, live stats dashboard
  * Global error reporter that DMs the admin

Run:
    export BOT_TOKEN="..."          # required, from @BotFather
    export ADMIN_ID="..."           # required, your Telegram user id
    python exam_prep_bot.py
"""

import asyncio
import csv
import html
import json
import logging
import os
import random
import threading
import time
import traceback
from datetime import datetime, time as dtime, timedelta
from io import BytesIO, StringIO
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Update,
    WebAppInfo,
)
from telegram.constants import ChatAction
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ================== SYSTEM CONFIGURATION ==================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
DEFAULT_MINI_APP_URL = os.getenv(
    "MINI_APP_URL", "https://mocktest-pro-lknw.onrender.com/"
)
PORT = int(os.getenv("PORT", 8080))
DB_FILE = os.getenv("DB_FILE", os.path.join(os.getcwd(), "bot_database.json"))
BACKUP_FILE = os.getenv("BACKUP_FILE", os.path.join(os.getcwd(), "bot_database_backup.json"))

# Game rules
QUIZ_SIZE = int(os.getenv("QUIZ_SIZE", "10"))
QUESTION_TIME = int(os.getenv("QUESTION_TIME", "20"))
COINS_PER_CORRECT = 5
COOLDOWN_TIME = 2.0
CATEGORIES = ["Aptitude", "Reasoning", "General Knowledge", "English", "Technical"]
DIFFICULTIES = ["Any", "Easy", "Medium", "Hard"]
# ==========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Core state
db_lock = asyncio.Lock()
user_cooldowns: dict[int, float] = {}
quiz_sessions: dict[int, dict] = {}
pending_admin: dict[int, dict] = {}

# ================== CLOUD UPTIME NODE (Render / any host) ==================
class UptimeNodeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Enterprise Core Server is Online & Active [Level 200].")

    def log_message(self, fmt, *args):
        pass


def start_uptime_node():
    try:
        server = HTTPServer(("0.0.0.0", PORT), UptimeNodeHandler)
        logger.info(f"Cloud Uptime Node running on port {PORT}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Uptime node failed to start: {e}")


# ================== HELPER FUNCTIONS ==================
def esc(text) -> str:
    """Bulletproof HTML escaper for any user/content input."""
    return html.escape(str(text), quote=False) if text else "N/A"


def get_ist_time() -> str:
    ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    return ist.strftime("%Y-%m-%d %I:%M %p")


def get_ist_date() -> str:
    ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    return ist.strftime("%Y-%m-%d")


def ist_to_utc_time(hour: int, minute: int):
    """Convert an IST clock time into a naive UTC time for run_daily."""
    total = (hour * 60 + minute - 330) % 1440
    return dtime(total // 60, total % 60)


async def check_spam(user_id: int) -> bool:
    """True if the user is hitting commands too fast (admin exempt)."""
    if user_id == ADMIN_ID:
        return False
    now = time.time()
    if now - user_cooldowns.get(user_id, 0) < COOLDOWN_TIME:
        return True
    user_cooldowns[user_id] = now
    return False


async def show_typing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        if chat:
            await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
    except Exception:
        pass


# ================== SEED QUESTION BANK ==================
def build_seed_questions():
    q = [
        # ----- Aptitude -----
        {
            "id": 1, "category": "Aptitude", "difficulty": "Easy",
            "question": "A train 300 m long crosses a pole in 15 seconds. What is its speed?",
            "options": ["54 km/h", "60 km/h", "72 km/h", "80 km/h"], "correct": 2,
            "explanation": "Speed = Distance / Time = 300 m / 15 s = 20 m/s = 20 × 18/5 = 72 km/h.",
        },
        {
            "id": 2, "category": "Aptitude", "difficulty": "Medium",
            "question": "If x + 1/x = 3, then what is x² + 1/x²?",
            "options": ["5", "7", "9", "11"], "correct": 1,
            "explanation": "x² + 1/x² = (x + 1/x)² − 2 = 9 − 2 = 7.",
        },
        {
            "id": 3, "category": "Aptitude", "difficulty": "Medium",
            "question": "Simple interest on ₹5,000 at 8% per annum for 2 years is:",
            "options": ["₹600", "₹700", "₹800", "₹900"], "correct": 2,
            "explanation": "SI = P×R×T/100 = 5000×8×2/100 = ₹800.",
        },
        {
            "id": 4, "category": "Aptitude", "difficulty": "Hard",
            "question": "The LCM of 12, 18 and 24 is:",
            "options": ["36", "48", "72", "144"], "correct": 2,
            "explanation": "12=2²×3, 18=2×3², 24=2³×3 → LCM = 2³×3² = 72.",
        },
        {
            "id": 5, "category": "Aptitude", "difficulty": "Easy",
            "question": "A shopkeeper sells an item at ₹450 after a 10% discount. The marked price was:",
            "options": ["₹495", "₹500", "₹505", "₹510"], "correct": 1,
            "explanation": "90% of marked price = 450 → marked price = 450 × 100/90 = ₹500.",
        },
        # ----- Reasoning -----
        {
            "id": 6, "category": "Reasoning", "difficulty": "Easy",
            "question": "Which one does NOT belong to the group?",
            "options": ["Apple", "Mango", "Potato", "Orange"], "correct": 2,
            "explanation": "Apple, Mango and Orange are fruits; Potato is a vegetable.",
        },
        {
            "id": 7, "category": "Reasoning", "difficulty": "Medium",
            "question": "Complete the series: 2, 6, 12, 20, 30, ?",
            "options": ["40", "42", "44", "46"], "correct": 1,
            "explanation": "Differences are 4, 6, 8, 10 → next difference 12 → 30 + 12 = 42.",
        },
        {
            "id": 8, "category": "Reasoning", "difficulty": "Medium",
            "question": "If ROSE is coded as SPTF, how is LILY coded?",
            "options": ["MJMZ", "MJMX", "MKMZ", "NJMZ"], "correct": 0,
            "explanation": "Each letter moves one step forward: L→M, I→J, L→M, Y→Z.",
        },
        {
            "id": 9, "category": "Reasoning", "difficulty": "Easy",
            "question": "A is 4th from the left in a row of 10. What is his position from the right?",
            "options": ["6th", "7th", "8th", "9th"], "correct": 1,
            "explanation": "Position from right = 10 − 4 + 1 = 7th.",
        },
        {
            "id": 10, "category": "Reasoning", "difficulty": "Hard",
            "question": "If P means +, Q means −, R means ×, S means ÷, then 8 R 4 S 2 Q 5 P 3 = ?",
            "options": ["14", "16", "18", "20"], "correct": 0,
            "explanation": "8×4÷2−5+3 = 16−5+3 = 14 (apply × and ÷ first).",
        },
        # ----- General Knowledge -----
        {
            "id": 11, "category": "General Knowledge", "difficulty": "Easy",
            "question": "What is the capital of Australia?",
            "options": ["Sydney", "Melbourne", "Canberra", "Perth"], "correct": 2,
            "explanation": "Canberra is the capital; Sydney and Melbourne are larger cities.",
        },
        {
            "id": 12, "category": "General Knowledge", "difficulty": "Easy",
            "question": "Which is the largest planet in our solar system?",
            "options": ["Earth", "Saturn", "Jupiter", "Neptune"], "correct": 2,
            "explanation": "Jupiter is the largest planet by both mass and volume.",
        },
        {
            "id": 13, "category": "General Knowledge", "difficulty": "Medium",
            "question": "What is the currency of Japan?",
            "options": ["Won", "Yen", "Yuan", "Ringgit"], "correct": 1,
            "explanation": "Japan uses the Yen; Won (Korea), Yuan (China), Ringgit (Malaysia).",
        },
        {
            "id": 14, "category": "General Knowledge", "difficulty": "Easy",
            "question": "When is India's Independence Day celebrated?",
            "options": ["26 January", "15 August", "2 October", "14 November"], "correct": 1,
            "explanation": "India gained independence on 15 August 1947.",
        },
        {
            "id": 15, "category": "General Knowledge", "difficulty": "Medium",
            "question": "Which gas is most abundant in Earth's atmosphere?",
            "options": ["Oxygen", "Carbon dioxide", "Nitrogen", "Argon"], "correct": 2,
            "explanation": "Nitrogen makes up about 78% of the atmosphere.",
        },
        # ----- English -----
        {
            "id": 16, "category": "English", "difficulty": "Easy",
            "question": "Choose the synonym of \"Abundant\":",
            "options": ["Scarce", "Plentiful", "Rare", "Tiny"], "correct": 1,
            "explanation": "Abundant means existing in large quantities — plentiful.",
        },
        {
            "id": 17, "category": "English", "difficulty": "Medium",
            "question": "Choose the antonym of \"Transparent\":",
            "options": ["Clear", "Opaque", "Bright", "Thin"], "correct": 1,
            "explanation": "Transparent lets light through; opaque blocks it.",
        },
        {
            "id": 18, "category": "English", "difficulty": "Medium",
            "question": "Which spelling is correct?",
            "options": ["Acommodate", "Accomodate", "Accommodate", "Acommmodate"], "correct": 2,
            "explanation": "Accommodate has double 'c' and double 'm'.",
        },
        {
            "id": 19, "category": "English", "difficulty": "Easy",
            "question": "She ___ to school every day.",
            "options": ["go", "goes", "going", "gone"], "correct": 1,
            "explanation": "Third-person singular present tense: she goes.",
        },
        {
            "id": 20, "category": "English", "difficulty": "Hard",
            "question": "Identify the correctly punctuated sentence:",
            "options": [
                "Where are you going?",
                "Where are you going.",
                "Where are you going,",
                "Where are you going!",
            ], "correct": 0,
            "explanation": "A 'where' question ends with a question mark.",
        },
        # ----- Technical -----
        {
            "id": 21, "category": "Technical", "difficulty": "Easy",
            "question": "Which language runs natively in web browsers?",
            "options": ["Python", "Java", "JavaScript", "C++"], "correct": 2,
            "explanation": "JavaScript is the scripting language of the web.",
        },
        {
            "id": 22, "category": "Technical", "difficulty": "Easy",
            "question": "Which SQL command fetches data from a table?",
            "options": ["INSERT", "SELECT", "UPDATE", "DELETE"], "correct": 1,
            "explanation": "SELECT retrieves rows; the others modify data.",
        },
        {
            "id": 23, "category": "Technical", "difficulty": "Medium",
            "question": "What does CPU stand for?",
            "options": [
                "Central Processing Unit",
                "Computer Personal Unit",
                "Central Program Utility",
                "Control Processing Unit",
            ], "correct": 0,
            "explanation": "The CPU is the brain of the computer.",
        },
        {
            "id": 24, "category": "Technical", "difficulty": "Medium",
            "question": "Which data structure works on FIFO (First In, First Out)?",
            "options": ["Stack", "Queue", "Tree", "Graph"], "correct": 1,
            "explanation": "Queue is FIFO; Stack is LIFO (Last In, First Out).",
        },
        {
            "id": 25, "category": "Technical", "difficulty": "Hard",
            "question": "In HTTP, which status code means 'Not Found'?",
            "options": ["200", "301", "404", "500"], "correct": 2,
            "explanation": "404 = resource not found; 200 = OK; 301 = moved; 500 = server error.",
        },
    ]
    return q


# ================== ASYNC DATABASE ENGINE ==================
_save_counter = 0


def default_db() -> dict:
    return {
        "users": {},
        "banned_users": {},
        "maintenance": False,
        "questions": build_seed_questions(),
        "next_question_id": 1000,
        "config": {
            "mini_app_url": DEFAULT_MINI_APP_URL,
            "custom_api_key": "",
            "welcome_message": "",
        },
    }


async def load_db() -> dict:
    async with db_lock:
        default = default_db()
        if not os.path.exists(DB_FILE):
            return default
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return default
                data = json.loads(content)
            # Merge in missing structure (keeps old DBs compatible)
            for key in default:
                data.setdefault(key, default[key])
            for key in default["config"]:
                data["config"].setdefault(key, default["config"][key])
            if not isinstance(data.get("questions"), list) or not data["questions"]:
                data["questions"] = default["questions"]
            return data
        except Exception as e:
            logger.error(f"DB Read Error: {e}")
            return default


async def save_db(data: dict):
    global _save_counter
    async with db_lock:
        try:
            tmp = DB_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, DB_FILE)
            _save_counter += 1
            # Rolling auto-backup every 30 writes
            if _save_counter % 30 == 0:
                with open(BACKUP_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                logger.info("Auto-backup written.")
        except Exception as e:
            logger.error(f"DB Save Error: {e}")


async def register_or_update_user(user) -> bool:
    db = await load_db()
    uid = str(user.id)
    is_new = uid not in db["users"]
    now = get_ist_time()
    u = db["users"].get(uid, {})
    u.setdefault("first_name", user.first_name or "N/A")
    u.setdefault("last_name", user.last_name or "")
    u.setdefault("username", user.username or "")
    u.setdefault("joined_at", now)
    u["last_active"] = now
    u.setdefault("stats", {
        "coins": 0, "correct": 0, "wrong": 0, "total": 0,
        "quizzes": 0, "streak": 0, "last_quiz_date": "",
    })
    db["users"][uid] = u
    await save_db(db)
    return is_new


# ================== GAMIFICATION ==================
def update_stats(uid: str, db: dict, correct: int, answered: int, coins: int):
    stats = db["users"][uid]["stats"]
    stats["coins"] += coins
    stats["correct"] += correct
    stats["wrong"] += answered - correct
    stats["total"] += answered
    stats["quizzes"] += 1
    today = get_ist_date()
    yesterday = (
        datetime.utcnow() + timedelta(hours=5, minutes=30) - timedelta(days=1)
    ).strftime("%Y-%m-%d")
    last = stats.get("last_quiz_date", "")
    if last == today:
        stats["streak"] = stats.get("streak", 0)
    elif last == yesterday:
        stats["streak"] = stats.get("streak", 0) + 1
    else:
        stats["streak"] = 1
    stats["last_quiz_date"] = today


def rank_of(uid: str, db: dict) -> int:
    ranked = sorted(
        db["users"].items(),
        key=lambda kv: (kv[1]["stats"]["coins"], kv[1]["stats"]["correct"]),
        reverse=True,
    )
    for i, (u, _) in enumerate(ranked):
        if u == uid:
            return i + 1
    return 0


# ================== UI BUILDERS ==================
async def get_welcome_text(user_name: str) -> str:
    db = await load_db()
    custom = db.get("config", {}).get("welcome_message", "")
    safe_name = esc(user_name)
    if custom:
        return custom.replace("{name}", safe_name)
    return (
        f"👋 <b>Hey {safe_name}!</b> Welcome to <b>ExamPrep Arena</b> 🚀\n\n"
        f"⚡ <i>Your Ultimate Destination for Smart Practice & High-Score Prep!</i>\n\n"
        f"🔥 <b>What's in store for you?</b>\n"
        f"• 🎯 <b>Exam-Level Mock Tests</b> — real questions & pattern drills\n"
        f"• 🎮 <b>In-Chat Quizzes</b> — timed questions with instant explanations\n"
        f"• 🪙 <b>Coins & Streaks</b> — earn coins, keep your daily streak alive\n"
        f"• 🏆 <b>Leaderboard</b> — climb the arena rankings\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 <b>Ready to test your knowledge? Tap below to jump in!</b>"
    )


def get_welcome_markup(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Open Test Arena", web_app=WebAppInfo(url=url))],
        [
            InlineKeyboardButton("🎮 Take a Quiz", callback_data="quiz_start"),
            InlineKeyboardButton("👤 My Profile", callback_data="welcome:profile"),
        ],
        [
            InlineKeyboardButton("🏆 Leaderboard", callback_data="top_page:1"),
            InlineKeyboardButton("📜 Terms", callback_data="welcome:terms"),
        ],
    ])


# ================== STARTUP & ALERTS ==================
async def post_init_setup(application: Application):
    commands = [
        BotCommand("start", "Launch bot & open the arena"),
        BotCommand("quiz", "Take a timed in-chat quiz"),
        BotCommand("top", "View the arena leaderboard"),
        BotCommand("profile", "Check your profile & stats"),
        BotCommand("remindme", "Set a daily practice reminder (HH:MM)"),
        BotCommand("help", "How to use this bot"),
        BotCommand("terms", "View Terms & Guidelines"),
    ]
    await application.bot.set_my_commands(commands)

    db = await load_db()
    app_url = db["config"]["mini_app_url"]
    try:
        await application.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="🚀 Open Arena", web_app=WebAppInfo(url=app_url)
            )
        )
    except Exception:
        pass

    # Re-arm daily reminders for every user who set one
    if application.job_queue:
        for uid, u in db.get("users", {}).items():
            rem = u.get("reminder", "")
            if rem and ":" in rem:
                try:
                    h, m = map(int, rem.split(":"))
                    application.job_queue.run_daily(
                        daily_reminder_job,
                        time=ist_to_utc_time(h, m),
                        name=f"remind_{uid}",
                        data={"uid": uid},
                    )
                except Exception:
                    pass

    try:
        await application.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"🟢 <b>System Online!</b> Enterprise Core [Level 200] booted at "
                f"{get_ist_time()}.\n👥 Users: {len(db.get('users', {}))} · "
                f"❓ Questions: {len(db.get('questions', []))}"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Boot alert failed: {e}")
    logger.info("Bot Level 200 initialization completed.")


async def daily_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data or {}
    uid = data.get("uid")
    if not uid:
        return
    db = await load_db()
    u = db.get("users", {}).get(str(uid))
    if not u:
        return
    name = esc(u.get("first_name", "Aspirant"))
    text = (
        f"⏰ <b>Daily Practice Reminder!</b>\n\n"
        f"Hey {name}, your streak depends on you! 🔥\n"
        f"Just 10 quick questions a day keeps the rust away.\n\n"
        f"👇 <b>Tap below to start your quiz!</b>"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 Start Quiz", callback_data="quiz_start")],
        [InlineKeyboardButton("🚀 Open Arena", web_app=WebAppInfo(url=(await load_db())["config"]["mini_app_url"]))],
    ])
    try:
        await context.bot.send_message(chat_id=int(uid), text=text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass


# ================== QUIZ ENGINE ==================
def build_quiz(category: str, difficulty: str, questions: list) -> list:
    pool = [q for q in questions if q.get("category") == category]
    if difficulty != "Any":
        pool = [q for q in pool if q.get("difficulty") == difficulty]
    if not pool:
        pool = [q for q in questions if q.get("category") == category]
    if not pool:
        return []
    random.shuffle(pool)
    return pool[:QUIZ_SIZE]


def cancel_question_timer(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    try:
        if context.job_queue:
            for job in context.job_queue.get_jobs_by_name(f"qt_{chat_id}"):
                job.schedule_removal()
    except Exception:
        pass


async def render_question(chat_id: int, context: ContextTypes.DEFAULT_TYPE, session: dict, edit: bool):
    idx = session["idx"]
    q = session["questions"][idx]
    total = len(session["questions"])
    text = (
        f"📝 <b>Question {idx + 1}/{total}</b> · {esc(q.get('category', ''))} · {esc(q.get('difficulty', ''))}\n"
        f"⏱️ <i>{QUESTION_TIME}s on the clock — answer fast!</i>\n\n"
        f"<b>{esc(q['question'])}</b>"
    )
    labels = ["A", "B", "C", "D"]
    rows = []
    opts = q.get("options", [])
    for i in range(0, len(opts), 2):
        row = []
        for j in range(i, min(i + 2, len(opts))):
            label = labels[j] if j < len(labels) else str(j + 1)
            opt_text = esc(opts[j])[:40]
            row.append(InlineKeyboardButton(f"{label}) {opt_text}", callback_data=f"answer:{j}"))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("⏭️ Skip", callback_data="answer:99"),
        InlineKeyboardButton("🏁 End Quiz", callback_data="quiz_end"),
    ])
    cancel_question_timer(context, chat_id)
    context.job_queue.run_once(
        question_timer_cb, when=QUESTION_TIME, data={"chat_id": chat_id, "idx": idx}, name=f"qt_{chat_id}"
    )
    if edit:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=session["qmsg_id"], text=text,
                reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML",
            )
        except Exception:
            msg = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")
            session["qmsg_id"] = msg.message_id
    else:
        msg = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")
        session["qmsg_id"] = msg.message_id


async def question_timer_cb(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data or {}
    chat_id = data.get("chat_id")
    idx = data.get("idx")
    session = quiz_sessions.get(chat_id)
    if not session or session["idx"] != idx:
        return
    q = session["questions"][idx]
    session["answers"].append({"question": q, "chosen": -1})
    session["total"] += 1
    opt = esc(q["options"][q["correct"]])
    expl = esc(q.get("explanation", ""))
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=session["qmsg_id"],
            text=(
                f"⏰ <b>Time's up!</b>\n\n"
                f"✅ Correct answer: <b>{opt}</b>\n"
                f"💡 <i>{expl}</i>"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass
    session["idx"] += 1
    if session["idx"] >= len(session["questions"]):
        await finish_quiz(chat_id, context, session)
    else:
        await render_question(chat_id, context, session, edit=False)


async def finish_quiz(chat_id: int, context: ContextTypes.DEFAULT_TYPE, session: dict):
    cancel_question_timer(context, chat_id)
    if chat_id in quiz_sessions:
        del quiz_sessions[chat_id]
    correct = session["correct"]
    answered = session["total"]
    total = len(session["questions"])
    wrong = max(0, answered - correct)
    skipped = max(0, total - answered)
    acc = round(correct / total * 100) if total else 0
    coins = correct * COINS_PER_CORRECT
    elapsed = int(time.time() - session["q_start"])

    db = await load_db()
    uid = str(session["uid"])
    update_stats(uid, db, correct, answered, coins)
    await save_db(db)
    streak = db["users"][uid]["stats"].get("streak", 0)
    rank = rank_of(uid, db)

    text = (
        f"🏁 <b>QUIZ COMPLETE!</b>\n\n"
        f"✅ <b>Correct:</b> {correct}\n"
        f"❌ <b>Wrong:</b> {wrong}\n"
        f"⏭️ <b>Skipped:</b> {skipped}\n"
        f"🎯 <b>Accuracy:</b> {acc}%\n"
        f"🪙 <b>Coins earned:</b> +{coins}\n"
        f"🔥 <b>Streak:</b> {streak} day{'s' if streak != 1 else ''}\n"
        f"⏱️ <b>Time:</b> {elapsed}s\n\n"
        f"📊 <b>Leaderboard rank:</b> #{rank if rank else '—'}"
    )
    cat = session["questions"][0].get("category", "") if session["questions"] else ""
    diff = session["questions"][0].get("difficulty", "") if session["questions"] else "Any"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Retake Quiz", callback_data=f"quiz_retake:{cat}|{diff}")],
        [
            InlineKeyboardButton("🏆 Leaderboard", callback_data="top_page:1"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="welcome:back"),
        ],
    ])
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=session["qmsg_id"], text=text,
            reply_markup=keyboard, parse_mode="HTML",
        )
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode="HTML")


# ================== CORE USER HANDLERS ==================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        if not user or not update.message:
            return
        if await check_spam(user.id):
            return
        await show_typing(update, context)

        db = await load_db()
        chat_id = update.effective_chat.id
        uid = str(user.id)

        if uid in db.get("banned_users", {}):
            await context.bot.send_message(
                chat_id=chat_id, text="🚫 <b>Access Denied:</b> You are banned.", parse_mode="HTML"
            )
            return

        is_new = await register_or_update_user(user)

        if is_new and user.id != ADMIN_ID:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        f"🔔 <b>New Aspirant!</b>\n👤 Name: {esc(user.first_name)}\n"
                        f"🔗 @{esc(user.username)}\n🆔 <code>{user.id}</code>\n⏰ {get_ist_time()}"
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass

        if db.get("maintenance", False) and user.id != ADMIN_ID:
            await context.bot.send_message(
                chat_id=chat_id,
                text="🛠️ <b>Maintenance in Progress.</b> Please check back shortly!",
                parse_mode="HTML",
            )
            return

        user_name = user.first_name if user.first_name else "Aspirant"
        app_url = db["config"]["mini_app_url"]
        welcome_text = await get_welcome_text(user_name)
        await context.bot.send_message(
            chat_id=chat_id, text=welcome_text, reply_markup=get_welcome_markup(app_url), parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error in start_command: {e}")


async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_spam(update.effective_user.id):
        return
    db = await load_db()
    if str(update.effective_user.id) in db.get("banned_users", {}):
        return
    keyboard = [[InlineKeyboardButton("🚀 Launch Test Arena", web_app=WebAppInfo(url=db["config"]["mini_app_url"]))]]
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="📝 <b>Click below to launch:</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_spam(update.effective_user.id):
        return
    await show_typing(update, context)
    rows = []
    for c in CATEGORIES:
        rows.append([InlineKeyboardButton(f"📚 {c}", callback_data=f"cat:{c}")])
    keyboard = InlineKeyboardMarkup(rows)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🎮 <b>CHOOSE YOUR BATTLEFIELD</b>\n\nPick a category to start your timed quiz:",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_spam(update.effective_user.id):
        return
    await show_typing(update, context)
    user = update.effective_user
    db = await load_db()
    uid = str(user.id)
    u = db.get("users", {}).get(uid, {})
    stats = u.get("stats", {})
    joined = u.get("joined_at", "N/A")
    status = "🔴 Banned" if uid in db.get("banned_users", {}) else "🟢 Active"
    total = stats.get("total", 0)
    acc = round(stats.get("correct", 0) / total * 100) if total else 0
    rank = rank_of(uid, db)
    text = (
        f"👤 <b>YOUR PROFILE</b>\n\n"
        f"📛 <b>Name:</b> {esc(user.first_name)}\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
        f"📅 <b>Joined:</b> <code>{joined}</code>\n"
        f"🛡️ <b>Status:</b> {status}\n\n"
        f"🪙 <b>Coins:</b> {stats.get('coins', 0)}\n"
        f"🔥 <b>Streak:</b> {stats.get('streak', 0)} day(s)\n"
        f"🎯 <b>Accuracy:</b> {acc}%\n"
        f"📊 <b>Quizzes:</b> {stats.get('quizzes', 0)}\n"
        f"🏆 <b>Rank:</b> #{rank if rank else '—'}"
    )
    await context.bot.send_message(chat_id=user.id, text=text, parse_mode="HTML")


async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_spam(update.effective_user.id):
        return
    await send_leaderboard_page(update.effective_chat.id, 1, context)


async def remindme_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_spam(update.effective_user.id):
        return
    user = update.effective_user
    uid = str(user.id)
    if not context.args:
        return await update.message.reply_text(
            "⏰ <b>Usage:</b> <code>/remindme 19:30</code>\n"
            "*(24-hour IST time. Use `/remindme off` to disable.)*",
            parse_mode="HTML",
        )
    arg = context.args[0].lower()
    db = await load_db()
    if arg == "off":
        db["users"].get(uid, {}).pop("reminder", None)
        await save_db(db)
        if context.job_queue:
            for job in context.job_queue.get_jobs_by_name(f"remind_{uid}"):
                job.schedule_removal()
        return await update.message.reply_text("✅ <b>Daily reminder turned OFF.</b>", parse_mode="HTML")
    try:
        h, m = map(int, arg.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
    except Exception:
        return await update.message.reply_text(
            "⚠️ <b>Invalid time.</b> Use 24-hour format like <code>/remindme 19:30</code> (IST).",
            parse_mode="HTML",
        )
    db["users"].setdefault(uid, {})["reminder"] = f"{h:02d}:{m:02d}"
    await save_db(db)
    if context.job_queue:
        for job in context.job_queue.get_jobs_by_name(f"remind_{uid}"):
            job.schedule_removal()
        context.job_queue.run_daily(
            daily_reminder_job, time=ist_to_utc_time(h, m), name=f"remind_{uid}", data={"uid": uid}
        )
    await update.message.reply_text(
        f"✅ <b>Daily reminder set!</b> I'll ping you at <code>{h:02d}:{m:02d}</code> IST every day. 🔥",
        parse_mode="HTML",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_spam(update.effective_user.id):
        return
    text = (
        "💡 <b>HOW TO USE THIS BOT</b>\n\n"
        "1️⃣ <b>/quiz</b> — take a timed in-chat quiz (pick category & difficulty)\n"
        "2️⃣ <b>/top</b> — view the arena leaderboard\n"
        "3️⃣ <b>/profile</b> — your coins, streak, accuracy & rank\n"
        "4️⃣ <b>/remindme 19:30</b> — daily practice reminder (IST)\n"
        "5️⃣ <b>/test</b> — open the full test arena web app\n"
        "6️⃣ <b>/terms</b> — read our rules\n\n"
        "<i>Correct answers earn +5 🪙. Keep your streak alive daily!</i>"
    )
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="HTML")


async def terms_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_spam(update.effective_user.id):
        return
    text = (
        "📜 <b>TERMS & GUIDELINES</b>\n\n"
        "• This bot is for <b>educational practice</b> only.\n"
        "• Do not spam, flood or misuse the bot.\n"
        "• Coins & streaks are gamification, not real currency.\n"
        "• Misuse may result in a permanent ban.\n"
        "• The admin reserves the right to modify rules anytime.\n\n"
        "<i>Practice hard, succeed faster! 🚀</i>"
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="welcome:back")]])
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=keyboard, parse_mode="HTML")


# ================== LEADERBOARD ==================
async def send_leaderboard_page(chat_id: int, page: int, context: ContextTypes.DEFAULT_TYPE):
    db = await load_db()
    users = db.get("users", {})
    ranked = sorted(
        users.values(), key=lambda r: (r["stats"]["coins"], r["stats"]["correct"]), reverse=True
    )
    page_size = 10
    total_pages = max(1, (len(ranked) + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    chunk = ranked[(page - 1) * page_size : page * page_size]

    lines = [f"🏆 <b>ARENA LEADERBOARD</b> · Page {page}/{total_pages}\n"]
    if not chunk:
        lines.append("No competitors yet — take a quiz to claim the throne! 👑")
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(chunk):
        rank = (page - 1) * page_size + i + 1
        medal = medals[rank - 1] if rank <= 3 else f"{rank}."
        name = esc(r.get("first_name", "?"))
        if r.get("username"):
            name += f" (@{esc(r['username'])})"
        lines.append(
            f"{medal} <b>{name}</b>\n"
            f"    🪙 {r['stats']['coins']} · ✅ {r['stats']['correct']}/{r['stats']['total']} · 🔥 {r['stats']['streak']}d"
        )
    text = "\n".join(lines)

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"top_page:{page - 1}"))
    nav.append(InlineKeyboardButton("🏠 Menu", callback_data="welcome:back"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"top_page:{page + 1}"))
    keyboard = InlineKeyboardMarkup([nav])
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode="HTML")


# ================== CALLBACK HANDLERS ==================
async def quiz_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rows = []
    for c in CATEGORIES:
        rows.append([InlineKeyboardButton(f"📚 {c}", callback_data=f"cat:{c}")])
    keyboard = InlineKeyboardMarkup(rows)
    try:
        await query.edit_message_text(
            text="🎮 <b>CHOOSE YOUR BATTLEFIELD</b>\n\nPick a category to start your timed quiz:",
            reply_markup=keyboard, parse_mode="HTML",
        )
    except BadRequest:
        pass


async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat = query.data.split(":", 1)[1]
    rows = []
    for d in DIFFICULTIES:
        rows.append([InlineKeyboardButton(f"🎚️ {d}", callback_data=f"diff:{cat}|{d}")])
    keyboard = InlineKeyboardMarkup(rows)
    try:
        await query.edit_message_text(
            text=f"📚 <b>{esc(cat)}</b>\n\nNow pick a difficulty level:",
            reply_markup=keyboard, parse_mode="HTML",
        )
    except BadRequest:
        pass


async def difficulty_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat, diff = query.data.split(":", 1)[1].split("|", 1)
    db = await load_db()
    questions = build_quiz(cat, diff, db.get("questions", []))
    if not questions:
        try:
            await query.edit_message_text(
                text="⚠️ No questions available for this selection yet. Try another category!",
                parse_mode="HTML",
            )
        except BadRequest:
            pass
        return
    user = update.effective_user
    session = {
        "uid": user.id,
        "questions": questions,
        "idx": 0,
        "correct": 0,
        "total": 0,
        "answers": [],
        "q_start": time.time(),
        "qmsg_id": query.message.message_id,
    }
    quiz_sessions[query.message.chat_id] = session
    await render_question(query.message.chat_id, context, session, edit=True)


async def answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    session = quiz_sessions.get(chat_id)
    if not session:
        return
    user = update.effective_user
    if user.id != session["uid"]:
        return
    if session.get("answered") == session["idx"]:
        return  # double-tap guard
    chosen = int(query.data.split(":", 1)[1])
    cancel_question_timer(context, chat_id)
    q = session["questions"][session["idx"]]
    session["answered"] = session["idx"]
    session["answers"].append({"question": q, "chosen": chosen})
    session["total"] += 1
    is_last = session["idx"] + 1 >= len(session["questions"])
    correct = q["correct"]
    opt = esc(q["options"][correct])
    expl = esc(q.get("explanation", ""))

    if chosen == correct:
        session["correct"] += 1
        head = f"✅ <b>Correct! +{COINS_PER_CORRECT} 🪙</b>"
    elif chosen == 99:
        head = "⏭️ <b>Skipped</b>"
    else:
        head = f"❌ <b>Wrong!</b> You picked: {esc(q['options'][chosen]) if chosen < len(q['options']) else '—'}"

    text = (
        f"{head}\n\n"
        f"✅ Correct answer: <b>{opt}</b>\n"
        f"💡 <i>{expl}</i>\n\n"
        f"📊 Score: <b>{session['correct']}</b>/{session['total']}"
    )
    rows = [[InlineKeyboardButton("▶️ Next Question", callback_data=f"next:{session['idx'] + 1}")]]
    if not is_last:
        rows.append([InlineKeyboardButton("🏁 End Early", callback_data="quiz_end")])
    else:
        rows[0] = [InlineKeyboardButton("🏁 View Results", callback_data="quiz_end")]
    try:
        await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")
    except BadRequest:
        pass
    if is_last:
        session["idx"] += 1


async def next_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    session = quiz_sessions.get(chat_id)
    if not session:
        return
    idx = int(query.data.split(":", 1)[1])
    if idx != session["idx"] + 1:
        return  # stale or out-of-order tap
    session["idx"] = idx
    if idx >= len(session["questions"]):
        await finish_quiz(chat_id, context, session)
        return
    await render_question(chat_id, context, session, edit=True)


async def end_quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    session = quiz_sessions.get(chat_id)
    if not session:
        return
    session["idx"] = len(session["questions"])
    await finish_quiz(chat_id, context, session)


async def retake_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat, diff = query.data.split(":", 1)[1].split("|", 1)
    db = await load_db()
    questions = build_quiz(cat, diff, db.get("questions", []))
    chat_id = query.message.chat_id
    if not questions:
        await context.bot.send_message(chat_id=chat_id, text="⚠️ No questions available.", parse_mode="HTML")
        return
    session = {
        "uid": update.effective_user.id,
        "questions": questions,
        "idx": 0,
        "correct": 0,
        "total": 0,
        "answers": [],
        "q_start": time.time(),
        "qmsg_id": query.message.message_id,
    }
    quiz_sessions[chat_id] = session
    await render_question(chat_id, context, session, edit=True)


async def welcome_nav_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data.split(":", 1)[1]
    db = await load_db()
    user = update.effective_user

    if data == "back":
        name = user.first_name if user.first_name else "Aspirant"
        text = await get_welcome_text(name)
        keyboard = get_welcome_markup(db["config"]["mini_app_url"])
    elif data == "profile":
        uid = str(user.id)
        u = db.get("users", {}).get(uid, {})
        stats = u.get("stats", {})
        total = stats.get("total", 0)
        acc = round(stats.get("correct", 0) / total * 100) if total else 0
        rank = rank_of(uid, db)
        text = (
            f"👤 <b>YOUR PROFILE</b>\n\n"
            f"🪙 <b>Coins:</b> {stats.get('coins', 0)}\n"
            f"🔥 <b>Streak:</b> {stats.get('streak', 0)} day(s)\n"
            f"🎯 <b>Accuracy:</b> {acc}%\n"
            f"📊 <b>Quizzes:</b> {stats.get('quizzes', 0)}\n"
            f"🏆 <b>Rank:</b> #{rank if rank else '—'}"
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="welcome:back")]])
    elif data == "terms":
        text = (
            "📜 <b>TERMS & GUIDELINES</b>\n\n"
            "• For educational practice only.\n"
            "• No spam or misuse.\n"
            "• Coins & streaks are not real currency.\n"
            "• Misuse may result in a ban."
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="welcome:back")]])
    else:
        return
    try:
        await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode="HTML")
    except BadRequest:
        pass


async def top_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = int(query.data.split(":", 1)[1])
    chat_id = query.message.chat_id
    db = await load_db()
    users = db.get("users", {})
    ranked = sorted(
        users.values(), key=lambda r: (r["stats"]["coins"], r["stats"]["correct"]), reverse=True
    )
    page_size = 10
    total_pages = max(1, (len(ranked) + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    chunk = ranked[(page - 1) * page_size : page * page_size]

    lines = [f"🏆 <b>ARENA LEADERBOARD</b> · Page {page}/{total_pages}\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(chunk):
        rank = (page - 1) * page_size + i + 1
        medal = medals[rank - 1] if rank <= 3 else f"{rank}."
        name = esc(r.get("first_name", "?"))
        if r.get("username"):
            name += f" (@{esc(r['username'])})"
        lines.append(
            f"{medal} <b>{name}</b>\n"
            f"    🪙 {r['stats']['coins']} · ✅ {r['stats']['correct']}/{r['stats']['total']} · 🔥 {r['stats']['streak']}d"
        )
    text = "\n".join(lines)
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"top_page:{page - 1}"))
    nav.append(InlineKeyboardButton("🏠 Menu", callback_data="welcome:back"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"top_page:{page + 1}"))
    try:
        await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup([nav]), parse_mode="HTML")
    except BadRequest:
        pass


# ================== ADMIN PANEL & FLOWS ==================
def get_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Live Stats", callback_data="admin:stats"),
            InlineKeyboardButton("➕ Add Question", callback_data="admin:addq"),
        ],
        [
            InlineKeyboardButton("📝 Question Bank", callback_data="admin:qbank:1"),
            InlineKeyboardButton("📢 Broadcast", callback_data="admin:bcast"),
        ],
        [
            InlineKeyboardButton("🛠️ Toggle Maint.", callback_data="admin:maint"),
            InlineKeyboardButton("🔄 Refresh", callback_data="admin:refresh"),
        ],
    ])


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    text = (
        "👑 <b>ENTERPRISE DASHBOARD</b>\n\n"
        "<i>⚙️ System:</i>\n"
        "• <code>/seturl &lt;link&gt;</code> — Change app URL\n"
        "• <code>/setwelcome &lt;text&gt;</code> — Welcome msg ({name} = user's name)\n"
        "• <code>/config</code> — View config\n\n"
        "<i>📚 Questions:</i>\n"
        "• <code>/qlist [page]</code> — Browse bank\n"
        "• <code>/qedit &lt;id&gt;</code> — Edit a question\n"
        "• <code>/qdel &lt;id&gt;</code> — Delete a question\n\n"
        "<i>📢 Communication:</i>\n"
        "• <code>/broadcast &lt;msg&gt;</code> — Global announce\n"
        "• <code>/dm &lt;id&gt; &lt;msg&gt;</code> — Private message\n\n"
        "<i>🛡️ Moderation & Data:</i>\n"
        "• <code>/ban &lt;id&gt;</code> | <code>/unban &lt;id&gt;</code> | <code>/user &lt;id&gt;</code>\n"
        "• <code>/export</code> — CSV export · <code>/backup</code> — JSON backup\n\n"
        "<i>Quick Actions:</i>"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_admin_keyboard())


async def admin_stats_view(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    db = await load_db()
    users = db.get("users", {})
    questions = db.get("questions", [])
    total_correct = sum(u["stats"]["correct"] for u in users.values())
    total_answered = sum(u["stats"]["total"] for u in users.values())
    acc = round(total_correct / total_answered * 100) if total_answered else 0
    top = sorted(users.values(), key=lambda r: r["stats"]["coins"], reverse=True)[:5]
    lines = [
        f"📊 <b>SYSTEM STATISTICS</b>\n",
        f"👥 <b>Total Users:</b> {len(users)}",
        f"🚫 <b>Banned:</b> {len(db.get('banned_users', {}))}",
        f"❓ <b>Questions:</b> {len(questions)}",
        f"📝 <b>Quizzes Taken:</b> {sum(u['stats']['quizzes'] for u in users.values())}",
        f"🪙 <b>Coins Issued:</b> {sum(u['stats']['coins'] for u in users.values())}",
        f"🎯 <b>Avg Accuracy:</b> {acc}%",
        f"🛠️ <b>Maintenance:</b> {'🔴 ON' if db.get('maintenance') else '🟢 OFF'}\n",
        f"🏆 <b>Top 5:</b>",
    ]
    medals = ["🥇", "🥈", "🥉", "4.", "5."]
    for i, r in enumerate(top):
        lines.append(
            f"{medals[i]} {esc(r.get('first_name', '?'))} — 🪙 {r['stats']['coins']}"
        )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Dashboard", callback_data="admin:refresh")]])
    await context.bot.send_message(chat_id=chat_id, text="\n".join(lines), reply_markup=keyboard, parse_mode="HTML")


def admin_question_bank_text(db: dict, page: int) -> str:
    questions = db.get("questions", [])
    page_size = 10
    total_pages = max(1, (len(questions) + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    chunk = questions[(page - 1) * page_size : page * page_size]
    lines = [f"📝 <b>QUESTION BANK</b> · Page {page}/{total_pages} · {len(questions)} total\n"]
    for q in chunk:
        lines.append(
            f"<code>{q['id']}</code> | {esc(q['category'])} | {esc(q['difficulty'])} | {esc(q['question'])[:60]}"
        )
    return "\n".join(lines)


async def admin_qbank_view(chat_id: int, page: int, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    db = await load_db()
    text = admin_question_bank_text(db, page)
    nav = [InlineKeyboardButton("➕ Add", callback_data="admin:addq")]
    if page > 1:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"admin:qbank:{page - 1}"))
    nav.append(InlineKeyboardButton("🏠", callback_data="admin:refresh"))
    questions = db.get("questions", [])
    total_pages = max(1, (len(questions) + 9) // 10)
    if page < total_pages:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"admin:qbank:{page + 1}"))
    if edit:
        try:
            await context.bot.edit_message_text(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup([nav]), parse_mode="HTML")
        except BadRequest:
            pass
    else:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup([nav]), parse_mode="HTML")


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        return
    chat_id = query.message.chat_id
    data = query.data
    action = data.split(":", 1)[1] if ":" in data else data

    if action == "stats":
        await admin_stats_view(chat_id, context)
    elif action == "refresh":
        try:
            await query.edit_message_text(
                text="👑 <b>ENTERPRISE DASHBOARD</b>\nSelect an option below:",
                reply_markup=get_admin_keyboard(), parse_mode="HTML",
            )
        except BadRequest:
            pass
    elif action == "maint":
        db = await load_db()
        db["maintenance"] = not db.get("maintenance", False)
        await save_db(db)
        status = "🔴 ENABLED" if db["maintenance"] else "🟢 DISABLED"
        await query.answer(f"Maintenance {status}!", show_alert=True)
        try:
            await query.edit_message_reply_markup(reply_markup=get_admin_keyboard())
        except BadRequest:
            pass
    elif action == "addq":
        pending_admin[chat_id] = {"action": "addq", "step": 0, "data": {}}
        rows = [[InlineKeyboardButton(f"📚 {c}", callback_data=f"admin:qcat:{c}")] for c in CATEGORIES]
        try:
            await query.edit_message_text(
                text="➕ <b>ADD QUESTION</b> · Step 1/6\n\nChoose the category:",
                reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML",
            )
        except BadRequest:
            pass
    elif action.startswith("qcat:"):
        cat = action.split(":", 1)[1]
        flow = pending_admin.get(chat_id)
        if not flow or flow["action"] != "addq":
            return
        flow["data"]["category"] = cat
        flow["step"] = 1
        rows = [[InlineKeyboardButton(f"🎚️ {d}", callback_data=f"admin:qdiff:{d}")] for d in ["Easy", "Medium", "Hard"]]
        try:
            await query.edit_message_text(
                text=f"➕ <b>ADD QUESTION</b> · Step 2/6\n\nCategory: {esc(cat)}\n\nChoose the difficulty:",
                reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML",
            )
        except BadRequest:
            pass
    elif action.startswith("qdiff:"):
        diff = action.split(":", 1)[1]
        flow = pending_admin.get(chat_id)
        if not flow or flow["action"] != "addq":
            return
        flow["data"]["difficulty"] = diff
        flow["step"] = 2
        try:
            await query.edit_message_text(
                text=(
                    f"➕ <b>ADD QUESTION</b> · Step 3/6\n\n"
                    f"Category: {esc(flow['data']['category'])} · Difficulty: {esc(diff)}\n\n"
                    f"📝 <b>Now send the question text</b> (or /cancel to abort):"
                ),
                parse_mode="HTML",
            )
        except BadRequest:
            pass
    elif action.startswith("qbank:"):
        page = int(action.split(":", 1)[1])
        await admin_qbank_view(chat_id, page, context, edit=True)
    elif action == "bcast":
        pending_admin[chat_id] = {"action": "bcast", "step": 0, "data": {}}
        try:
            await query.edit_message_text(
                text="📢 <b>BROADCAST</b>\n\nSend the message to broadcast to all users (or /cancel):",
                parse_mode="HTML",
            )
        except BadRequest:
            pass
    elif action.startswith("qdel_confirm:"):
        qid = action.split(":", 1)[1]
        db = await load_db()
        db["questions"] = [q for q in db.get("questions", []) if str(q["id"]) != qid]
        await save_db(db)
        try:
            await query.edit_message_text(text=f"🗑️ <b>Question <code>{qid}</code> deleted.</b>", parse_mode="HTML")
        except BadRequest:
            pass
    else:
        try:
            await query.edit_message_text(text="👑 <b>ENTERPRISE DASHBOARD</b>", reply_markup=get_admin_keyboard(), parse_mode="HTML")
        except BadRequest:
            pass


# --- Guided admin text-flow steps ---
async def admin_flow_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text
    flow = pending_admin.get(chat_id)
    if not flow:
        return False

    if flow["action"] == "addq":
        step = flow["step"]
        d = flow["data"]
        if step == 2:
            d["question"] = text
            flow["step"] = 3
            await update.message.reply_text(
                "➕ <b>ADD QUESTION</b> · Step 4/6\n\n"
                "🔢 <b>Send the 4 options</b>, one per line:\n"
                "<code>Option 1\nOption 2\nOption 3\nOption 4</code>",
                parse_mode="HTML",
            )
        elif step == 3:
            opts = [line.strip() for line in text.splitlines() if line.strip()]
            if len(opts) != 4:
                return await update.message.reply_text(
                    "⚠️ Need exactly 4 options, one per line. Try again (or /cancel):",
                    parse_mode="HTML",
                )
            d["options"] = opts
            flow["step"] = 4
            await update.message.reply_text(
                "➕ <b>ADD QUESTION</b> · Step 5/6\n\n"
                "✅ <b>Which option is correct?</b> Reply with the number 1–4:",
                parse_mode="HTML",
            )
        elif step == 4:
            try:
                correct = int(text.strip())
                if not 1 <= correct <= 4:
                    raise ValueError
            except ValueError:
                return await update.message.reply_text("⚠️ Reply with a number between 1 and 4 (or /cancel):", parse_mode="HTML")
            d["correct"] = correct - 1
            flow["step"] = 5
            await update.message.reply_text(
                "➕ <b>ADD QUESTION</b> · Step 6/6\n\n"
                "💡 <b>Send the explanation</b> (or send <code>skip</code>):",
                parse_mode="HTML",
            )
        elif step == 5:
            d["explanation"] = "—" if text.strip().lower() == "skip" else text.strip()
            db = await load_db()
            qid = db.get("next_question_id", 1000)
            db["next_question_id"] = qid + 1
            db.setdefault("questions", []).append({
                "id": qid,
                "category": d["category"],
                "difficulty": d["difficulty"],
                "question": d["question"],
                "options": d["options"],
                "correct": d["correct"],
                "explanation": d["explanation"],
            })
            await save_db(db)
            pending_admin.pop(chat_id, None)
            await update.message.reply_text(
                f"✅ <b>Question #{qid} saved!</b>\n\n"
                f"📝 {esc(d['question'])}\n"
                f"🅰️ {esc(d['options'][0])}\n"
                f"🅱️ {esc(d['options'][1])}\n"
                f"🅲 {esc(d['options'][2])}\n"
                f"🅳 {esc(d['options'][3])}\n"
                f"✅ Correct: {d['correct'] + 1}\n"
                f"💡 {esc(d['explanation'])}",
                parse_mode="HTML",
            )
        return True

    if flow["action"] == "bcast":
        flow["data"]["msg"] = text
        preview = f"📢 <b>Broadcast Preview</b>\n\n{text}"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirm", callback_data="bcast:confirm"),
                InlineKeyboardButton("❌ Cancel", callback_data="bcast:cancel"),
            ]
        ])
        await update.message.reply_text(preview, reply_markup=keyboard, parse_mode="HTML")
        return True
    return False


async def broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        return
    chat_id = query.message.chat_id
    action = query.data.split(":", 1)[1]
    flow = pending_admin.pop(chat_id, None)

    if action == "cancel":
        try:
            await query.edit_message_text(text="❌ <b>Broadcast cancelled.</b>", parse_mode="HTML")
        except BadRequest:
            pass
        return
    if not flow or not flow["data"].get("msg"):
        return
    msg = flow["data"]["msg"]
    db = await load_db()
    users = db.get("users", {})
    total = len(users)
    try:
        await query.edit_message_text(text=f"⏳ <b>Broadcasting to {total} users...</b>", parse_mode="HTML")
    except BadRequest:
        pass
    success, blocked = 0, 0
    for i, uid in enumerate(users.keys()):
        try:
            await context.bot.send_message(chat_id=int(uid), text=msg, parse_mode="HTML")
            success += 1
        except RetryAfter as ra:
            await asyncio.sleep(ra.retry_after)
            try:
                await context.bot.send_message(chat_id=int(uid), text=msg, parse_mode="HTML")
                success += 1
            except Exception:
                blocked += 1
        except Exception:
            blocked += 1
        if (i + 1) % 15 == 0:
            await asyncio.sleep(0.05)
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"✅ <b>Broadcast Complete!</b>\n\n🟢 Delivered: {success}\n🚫 Blocked: {blocked}\n📊 Total: {total}",
        parse_mode="HTML",
    )


async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        return await update.message.reply_text("⚠️ <b>Usage:</b> <code>/broadcast &lt;msg&gt;</code>", parse_mode="HTML")
    msg = update.message.text.split(None, 1)[1]
    pending_admin[update.effective_chat.id] = {"action": "bcast", "data": {"msg": msg}}
    preview = f"📢 <b>Broadcast Preview</b>\n\n{msg}"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data="bcast:confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="bcast:cancel"),
        ]
    ])
    await update.message.reply_text(preview, reply_markup=keyboard, parse_mode="HTML")


async def broadcast_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    pending_admin.pop(update.effective_chat.id, None)
    await update.message.reply_text("❌ <b>Broadcast cancelled.</b>", parse_mode="HTML")


# --- Admin utility commands ---
async def admin_seturl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args or not context.args[0].startswith("http"):
        return await update.message.reply_text("⚠️ <b>Usage:</b> <code>/seturl https://link.com</code>", parse_mode="HTML")
    new_url = context.args[0]
    db = await load_db()
    db["config"]["mini_app_url"] = new_url
    await save_db(db)
    try:
        await context.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="🚀 Open Arena", web_app=WebAppInfo(url=new_url))
        )
    except Exception:
        pass
    await update.message.reply_text(f"✅ <b>URL Updated!</b>\n🔗 <code>{esc(new_url)}</code>", parse_mode="HTML")


async def admin_setwelcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        return await update.message.reply_text(
            "⚠️ <b>Usage:</b> <code>/setwelcome Hello {name}! Welcome.</code>\n*(Use `/setwelcome default` to reset)*",
            parse_mode="HTML",
        )
    new_text = update.message.text.split(None, 1)[1]
    db = await load_db()
    if new_text.lower() == "default":
        db["config"]["welcome_message"] = ""
        await update.message.reply_text("✅ <b>Welcome message reset to Default!</b>", parse_mode="HTML")
    else:
        db["config"]["welcome_message"] = new_text
        await update.message.reply_text("✅ <b>Custom Welcome Message Saved!</b>", parse_mode="HTML")
    await save_db(db)


async def admin_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    db = await load_db()
    cfg = db.get("config", {})
    text = (
        f"⚙️ <b>SYSTEM CONFIG</b>\n\n"
        f"🔗 <b>App URL:</b> <code>{esc(cfg.get('mini_app_url'))}</code>\n"
        f"🛠️ <b>Maintenance:</b> {'🔴 ON' if db.get('maintenance') else '🟢 OFF'}\n"
        f"👥 <b>Users:</b> {len(db.get('users', {}))}\n"
        f"❓ <b>Questions:</b> {len(db.get('questions', []))}\n"
        f"💬 <b>Custom welcome:</b> {'Set' if cfg.get('welcome_message') else 'Default'}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def admin_dm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(context.args) < 2:
        return await update.message.reply_text("⚠️ <b>Usage:</b> <code>/dm &lt;user_id&gt; &lt;msg&gt;</code>", parse_mode="HTML")
    target = context.args[0]
    text = update.message.text.split(None, 2)[2]
    try:
        await context.bot.send_message(chat_id=int(target), text=text, parse_mode="HTML")
        await update.message.reply_text(f"✅ Message sent to <code>{target}</code>.", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: <code>{esc(e)}</code>", parse_mode="HTML")


async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        return await update.message.reply_text("⚠️ <b>Usage:</b> <code>/ban &lt;id&gt;</code>", parse_mode="HTML")
    if context.args[0] == str(ADMIN_ID):
        return await update.message.reply_text("❌ Cannot ban Admin!", parse_mode="HTML")
    db = await load_db()
    db["banned_users"][context.args[0]] = {"banned_at": get_ist_time()}
    await save_db(db)
    await update.message.reply_text(f"🚫 <b>User Banned:</b> <code>{context.args[0]}</code>", parse_mode="HTML")


async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        return await update.message.reply_text("⚠️ <b>Usage:</b> <code>/unban &lt;id&gt;</code>", parse_mode="HTML")
    db = await load_db()
    if context.args[0] in db.get("banned_users", {}):
        del db["banned_users"][context.args[0]]
        await save_db(db)
        await update.message.reply_text(f"✅ User <code>{context.args[0]}</code> unbanned.", parse_mode="HTML")
    else:
        await update.message.reply_text("ℹ️ User is not banned.", parse_mode="HTML")


async def admin_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        return await update.message.reply_text("⚠️ <b>Usage:</b> <code>/user &lt;id&gt;</code>", parse_mode="HTML")
    db = await load_db()
    u = db.get("users", {}).get(context.args[0])
    if not u:
        return await update.message.reply_text("❌ User not found.", parse_mode="HTML")
    b = "🔴 YES" if context.args[0] in db.get("banned_users", {}) else "🟢 NO"
    stats = u.get("stats", {})
    await update.message.reply_text(
        f"👤 <b>DETAILS:</b>\n🆔 <code>{context.args[0]}</code>\n"
        f"📛 {esc(u.get('first_name'))}\n🔗 @{esc(u.get('username'))}\n"
        f"📅 {esc(u.get('joined_at'))}\n🚫 Banned: {b}\n"
        f"🪙 Coins: {stats.get('coins', 0)} · 🔥 Streak: {stats.get('streak', 0)}d",
        parse_mode="HTML",
    )


async def admin_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        await context.bot.send_chat_action(chat_id=ADMIN_ID, action=ChatAction.UPLOAD_DOCUMENT)
    except Exception:
        pass
    db = await load_db()
    users = db.get("users", {})
    if not users:
        return await update.message.reply_text("⚠️ No users found in database.")
    csv_file = StringIO()
    writer = csv.writer(csv_file)
    writer.writerow(["User ID", "First Name", "Last Name", "Username", "Joined At", "Last Active", "Coins", "Streak", "Quizzes", "Correct", "Total", "Accuracy %", "Is Banned"])
    banned = db.get("banned_users", {})
    for uid, u in users.items():
        stats = u.get("stats", {})
        total = stats.get("total", 0)
        acc = round(stats.get("correct", 0) / total * 100) if total else 0
        writer.writerow([
            uid, u.get("first_name"), u.get("last_name"), u.get("username"),
            u.get("joined_at"), u.get("last_active"),
            stats.get("coins", 0), stats.get("streak", 0), stats.get("quizzes", 0),
            stats.get("correct", 0), total, acc,
            "Yes" if uid in banned else "No",
        ])
    bio = BytesIO(csv_file.getvalue().encode("utf-8"))
    bio.name = f"Users_Export_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    await context.bot.send_document(
        chat_id=ADMIN_ID, document=bio,
        caption=f"📊 <b>User Export</b> · {len(users)} users",
        parse_mode="HTML",
    )


async def admin_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        await context.bot.send_chat_action(chat_id=ADMIN_ID, action=ChatAction.UPLOAD_DOCUMENT)
    except Exception:
        pass
    try:
        with open(DB_FILE, "rb") as f:
            await context.bot.send_document(
                chat_id=ADMIN_ID, document=f,
                filename=f"DB_Backup_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.json",
                caption="📂 <b>Raw Database Backup</b>",
                parse_mode="HTML",
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Backup Failed: <code>{esc(e)}</code>", parse_mode="HTML")


async def qlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    page = 1
    if context.args:
        try:
            page = int(context.args[0])
        except ValueError:
            pass
    await admin_qbank_view(update.effective_chat.id, page, context)


async def qdel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        return await update.message.reply_text("⚠️ <b>Usage:</b> <code>/qdel &lt;id&gt;</code>", parse_mode="HTML")
    qid = context.args[0]
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, delete", callback_data=f"admin:qdel_confirm:{qid}"),
            InlineKeyboardButton("❌ Cancel", callback_data="admin:refresh"),
        ]
    ])
    await update.message.reply_text(
        f"🗑️ <b>Delete question <code>{qid}</code>?</b>", reply_markup=keyboard, parse_mode="HTML"
    )


async def qedit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        return await update.message.reply_text("⚠️ <b>Usage:</b> <code>/qedit &lt;id&gt;</code>", parse_mode="HTML")
    qid = context.args[0]
    db = await load_db()
    q = next((x for x in db.get("questions", []) if str(x["id"]) == qid), None)
    if not q:
        return await update.message.reply_text(f"❌ Question <code>{qid}</code> not found.", parse_mode="HTML")
    pending_admin[update.effective_chat.id] = {"action": "editq", "step": 0, "data": q}
    await update.message.reply_text(
        f"✏️ <b>EDITING QUESTION #{qid}</b>\n\n"
        f"📝 Current: {esc(q['question'])}\n\n"
        f"Send the <b>new question text</b>, or send <code>keep</code> to leave it unchanged (or /cancel):",
        parse_mode="HTML",
    )


async def admin_editq_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    flow = pending_admin.get(chat_id)
    if not flow or flow["action"] != "editq":
        return False
    q = flow["data"]
    step = flow["step"]
    qid = q["id"]

    if step == 0:
        if text.lower() != "keep":
            q["question"] = text
        flow["step"] = 1
        opts = "\n".join(q["options"])
        await update.message.reply_text(
            f"✏️ <b>EDIT #{qid}</b> · Options\n\nCurrent options:\n<code>{opts}</code>\n\n"
            f"Send the <b>4 new options</b> one per line, or <code>keep</code>:",
            parse_mode="HTML",
        )
    elif step == 1:
        if text.lower() != "keep":
            new_opts = [line.strip() for line in text.splitlines() if line.strip()]
            if len(new_opts) != 4:
                return await update.message.reply_text("⚠️ Need exactly 4 options, one per line. Try again (or /cancel):", parse_mode="HTML")
            q["options"] = new_opts
        flow["step"] = 2
        await update.message.reply_text(
            f"✏️ <b>EDIT #{qid}</b> · Correct option\n\n"
            f"Which option is correct? Send a number 1–4, or <code>keep</code> (current: {q['correct'] + 1}):",
            parse_mode="HTML",
        )
    elif step == 2:
        if text.lower() != "keep":
            try:
                correct = int(text)
                if not 1 <= correct <= 4:
                    raise ValueError
            except ValueError:
                return await update.message.reply_text("⚠️ Send a number between 1 and 4, or `keep` (or /cancel):", parse_mode="HTML")
            q["correct"] = correct - 1
        flow["step"] = 3
        await update.message.reply_text(
            f"✏️ <b>EDIT #{qid}</b> · Explanation\n\n"
            f"Send the new explanation, or <code>keep</code> (current: {esc(q.get('explanation', ''))[:60]}):",
            parse_mode="HTML",
        )
    elif step == 3:
        if text.lower() != "keep":
            q["explanation"] = text
        db = await load_db()
        for i, x in enumerate(db.get("questions", [])):
            if str(x["id"]) == str(qid):
                db["questions"][i] = q
                break
        await save_db(db)
        pending_admin.pop(chat_id, None)
        await update.message.reply_text(
            f"✅ <b>Question #{qid} updated!</b>\n\n📝 {esc(q['question'])}\n"
            f"✅ Correct: {q['correct'] + 1} · 💡 {esc(q.get('explanation', ''))[:100]}",
            parse_mode="HTML",
        )
    return True


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending_admin.pop(update.effective_chat.id, None)
    await update.message.reply_text("❌ <b>Flow cancelled.</b>", parse_mode="HTML")


async def catch_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text or msg.text.startswith("/"):
        return
    chat_id = update.effective_chat.id
    if chat_id in pending_admin:
        if update.effective_user.id == ADMIN_ID:
            if await admin_flow_step(update, context):
                return
            if await admin_editq_flow(update, context):
                return
    await start_command(update, context)


# ================== GLOBAL ERROR REPORTER ==================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    tb = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    error_msg = f"⚠️ <b>SYSTEM ALERT</b>\n\n<pre>{esc(tb[-1500:])}</pre>"
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=error_msg, parse_mode="HTML")
    except Exception:
        pass


# ================== MAIN APP RUNNER ==================
def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit(
            "❌ BOT_TOKEN is not set.\n"
            "   export BOT_TOKEN=\"your_token_from_botfather\"\n"
            "   export ADMIN_ID=\"your_telegram_id\"\n"
            "   python exam_prep_bot.py"
        )
    if not ADMIN_ID:
        raise SystemExit("❌ ADMIN_ID is not set. export ADMIN_ID=\"your_telegram_id\"")

    threading.Thread(target=start_uptime_node, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init_setup).build()

    # User handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("test", test_command))
    app.add_handler(CommandHandler("quiz", quiz_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("top", top_command))
    app.add_handler(CommandHandler("remindme", remindme_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("terms", terms_command))
    app.add_handler(CommandHandler("cancel", cancel_command))

    # Quiz callbacks
    app.add_handler(CallbackQueryHandler(quiz_start_callback, pattern="^quiz_start$"))
    app.add_handler(CallbackQueryHandler(category_callback, pattern="^cat:"))
    app.add_handler(CallbackQueryHandler(difficulty_callback, pattern="^diff:"))
    app.add_handler(CallbackQueryHandler(answer_callback, pattern="^answer:"))
    app.add_handler(CallbackQueryHandler(next_callback, pattern="^next:"))
    app.add_handler(CallbackQueryHandler(end_quiz_callback, pattern="^quiz_end$"))
    app.add_handler(CallbackQueryHandler(retake_callback, pattern="^quiz_retake:"))

    # Navigation
    app.add_handler(CallbackQueryHandler(welcome_nav_callback, pattern="^welcome:"))
    app.add_handler(CallbackQueryHandler(top_page_callback, pattern="^top_page:"))
    app.add_handler(CallbackQueryHandler(broadcast_callback, pattern="^bcast:"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin:"))

    # Free-text routing (admin flows, then welcome)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, catch_all_messages))

    # Admin handlers
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("seturl", admin_seturl))
    app.add_handler(CommandHandler("setwelcome", admin_setwelcome))
    app.add_handler(CommandHandler("config", admin_config))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(CommandHandler("broadcast_cancel", broadcast_cancel_command))
    app.add_handler(CommandHandler("dm", admin_dm))
    app.add_handler(CommandHandler("ban", admin_ban))
    app.add_handler(CommandHandler("unban", admin_unban))
    app.add_handler(CommandHandler("user", admin_user_info))
    app.add_handler(CommandHandler("export", admin_export))
    app.add_handler(CommandHandler("backup", admin_backup))
    app.add_handler(CommandHandler("qlist", qlist_command))
    app.add_handler(CommandHandler("qdel", qdel_command))
    app.add_handler(CommandHandler("qedit", qedit_command))

    # Global error handler
    app.add_error_handler(error_handler)

    print("🚀 Enterprise Core [Level 200] is now online & polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
