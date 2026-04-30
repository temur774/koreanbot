"""
🇰🇷 Korean Vocabulary Learning Bot - V3 (TUZATILGAN)
Tuzatishlar:
1. 🎭 Mafia O'yini — Taklif havolasi ishlaydi, lobbyga olib kiradi
2. 🌐 Tarjima — Avval DB, keyin Google Translate (bepul) dan foydalanadi
3. 🧹 To'liq tozalash — dublikatlar + bo'sh maydonlar
"""

import asyncio
import json
import logging
import os
import random
import time
import urllib.parse
from datetime import date
from typing import Optional, Union
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
import aiosqlite
import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Document,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MaybeInaccessibleMessage,
)
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError(".env faylda BOT_TOKEN yo'q!")

ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "7897938164").split(",")))

DB_PATH = "korean_bot.db"
BATTLE_Q_COUNT = 5
BATTLE_TIMEOUT = 15
TYPING_TIMEOUT = 30
FONT_OTF_PATH = "/tmp/NotoSansKR.otf"

# ─── MAFIA SOZLAMALARI ────────────────────────────────────────────────────────
MAFIA_MIN_PLAYERS = 4
MAFIA_MAX_PLAYERS = 6
MAFIA_ROLES = {
    4: {"don": 1, "citizen": 2, "doctor": 1},
    5: {"don": 1, "citizen": 2, "doctor": 1, "detective": 1},
    6: {"don": 1, "mafia": 1, "citizen": 2, "doctor": 1, "detective": 1},
}
MAFIA_ROLE_NAMES = {
    "don":       "🔴 Don (Bosh Mafia)",
    "mafia":     "🔴 Mafia",
    "citizen":   "⚪ Fuqaro",
    "doctor":    "💚 Shifokor",
    "detective": "🔵 Detektiv",
}
MAFIA_ROLE_INFO = {
    "don":       "Siz BOSH MAFIYAsiz! Kecha kimni o'ldirishni siz hal qilasiz. Detektiv sizni tanimaydi.",
    "mafia":     "Siz MAFIYAsiz! Bosh mafia (Don) bilan birga fuqarolarni o'ldirasiz.",
    "citizen":   "Siz fuqarosiz. Ovoz bilan mafiachini topishga harakat qiling!",
    "doctor":    "Siz SHIFOKOR siz! Har kecha bir kishini saqlab qolishingiz mumkin.",
    "detective": "Siz DETEKTIV siz! Har kecha bir kishini tekshirib, u mafiami yoki yo'qligini bilasiz.",
}

# mafia_lobbies: {chat_id: {host, players: [user_id,...], started, phase, ...}}
mafia_lobbies: dict = {}
# mafia_games: {chat_id: {roles, alive, phase, night_actions, votes, round, ...}}
mafia_games: dict = {}

_import_diff_counter = 0


# ─── FONT ────────────────────────────────────────────────────────────────────

def prepare_korean_font() -> bool:
    if os.path.exists(FONT_OTF_PATH):
        return True
    ttc_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    if not os.path.exists(ttc_path):
        logger.warning("NotoSansCJK font topilmadi.")
        return False
    try:
        from fontTools.ttLib import TTCollection
        ttc = TTCollection(ttc_path)
        kr_font = ttc[1]
        kr_font.save(FONT_OTF_PATH)
        return True
    except Exception as e:
        logger.error(f"Font xato: {e}")
        return False


# ─── DATABASE ────────────────────────────────────────────────────────────────

async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            full_name   TEXT,
            score       INTEGER DEFAULT 0,
            wins        INTEGER DEFAULT 0,
            losses      INTEGER DEFAULT 0,
            streak      INTEGER DEFAULT 0,
            max_streak  INTEGER DEFAULT 0,
            lives       INTEGER DEFAULT 3,
            last_daily  TEXT,
            badges      TEXT DEFAULT '',
            difficulty  TEXT DEFAULT 'easy',
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS words (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            korean       TEXT NOT NULL,
            romanization TEXT,
            translation  TEXT NOT NULL,
            wrong1       TEXT NOT NULL,
            wrong2       TEXT NOT NULL,
            wrong3       TEXT,
            wrong4       TEXT,
            difficulty   TEXT DEFAULT 'easy',
            added_by     INTEGER
        );
        CREATE TABLE IF NOT EXISTS battle_queue (
            user_id    INTEGER PRIMARY KEY,
            joined_at  REAL
        );
        CREATE TABLE IF NOT EXISTS battles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            player1     INTEGER,
            player2     INTEGER,
            score1      INTEGER DEFAULT 0,
            score2      INTEGER DEFAULT 0,
            questions   TEXT,
            current_q   INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'active',
            started_at  REAL
        );
        CREATE TABLE IF NOT EXISTS battle_answers (
            battle_id  INTEGER,
            user_id    INTEGER,
            q_index    INTEGER,
            answered   INTEGER DEFAULT 0,
            correct    INTEGER DEFAULT 0,
            PRIMARY KEY (battle_id, user_id, q_index)
        );
        CREATE TABLE IF NOT EXISTS team_battle_queue (
            user_id    INTEGER PRIMARY KEY,
            team_side  TEXT NOT NULL,
            joined_at  REAL
        );
        CREATE TABLE IF NOT EXISTS team_battles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            red1        INTEGER,
            red2        INTEGER,
            blue1       INTEGER,
            blue2       INTEGER,
            red_score   INTEGER DEFAULT 0,
            blue_score  INTEGER DEFAULT 0,
            questions   TEXT,
            status      TEXT DEFAULT 'active',
            started_at  REAL
        );
        CREATE TABLE IF NOT EXISTS team_battle_answers (
            battle_id  INTEGER,
            user_id    INTEGER,
            q_index    INTEGER,
            answered   INTEGER DEFAULT 0,
            correct    INTEGER DEFAULT 0,
            PRIMARY KEY (battle_id, user_id, q_index)
        );
        CREATE TABLE IF NOT EXISTS typing_sessions (
            user_id    INTEGER PRIMARY KEY,
            word_id    INTEGER,
            correct_answer TEXT,
            start_time REAL,
            chat_id    INTEGER
        );
        CREATE TABLE IF NOT EXISTS mafia_games (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     INTEGER,
            players     TEXT,
            roles       TEXT,
            status      TEXT DEFAULT 'lobby',
            started_at  REAL
        );
        """)
        await db.commit()
        await seed_words(db)


async def seed_words(db: aiosqlite.Connection) -> None:
    rows = list(await db.execute_fetchall("SELECT COUNT(*) FROM words"))
    if rows[0][0] > 0:
        return
    sample_words = [
        ("가게", "kage", "Do'kon", "Narx", "Mebel", "Shahar", None, "easy"),
        ("학교", "hakgyo", "Maktab", "Kasalxona", "Do'kon", "Uy", None, "easy"),
        ("사랑", "sarang", "Muhabbat", "Nafrat", "Xursandlik", "G'azab", None, "easy"),
        ("물", "mul", "Suv", "Non", "Osh", "Choy", None, "easy"),
        ("고양이", "goyangi", "Mushuk", "It", "Qush", "Ot", None, "easy"),
        ("책", "chaek", "Kitob", "Daftar", "Qalam", "Ruchka", None, "easy"),
        ("맛있다", "masitda", "Mazali", "Achchiq", "Shirin", "Nordon", None, "medium"),
        ("친구", "chingu", "Do'st", "Dushman", "Qarindosh", "Qo'shni", None, "easy"),
        ("음식", "eumsik", "Ovqat", "Ichimlik", "Kiyim", "Uy-joy", None, "easy"),
        ("바다", "bada", "Dengiz", "Tog'", "Daryo", "Ko'l", None, "easy"),
        ("하늘", "haneul", "Osmon", "Yer", "Dengiz", "O'rmon", None, "easy"),
        ("아름답다", "areumdapda", "Chiroyli", "Xunuk", "Katta", "Kichik", None, "medium"),
        ("어렵다", "eoryeopda", "Qiyin", "Oson", "Katta", "Tez", None, "medium"),
        ("공부하다", "gongbuhada", "O'qimoq", "Yemoq", "Uxlamoq", "Yugumoq", None, "medium"),
        ("행복하다", "haengbokhada", "Baxtli", "Baxtsiz", "G'amgin", "Xafa", None, "medium"),
        ("날씨", "nalshi", "Ob-havo", "Vaqt", "Mavsim", "Yil", None, "easy"),
        ("시장", "sijang", "Bozor", "Bank", "Kutubxona", "Mehmonxona", None, "medium"),
        ("여행", "yeohaeng", "Sayohat", "Dam olish", "Ish", "O'qish", None, "medium"),
        ("음악", "eumak", "Musiqa", "Rasm", "Kino", "Sport", None, "easy"),
        ("병원", "byeongwon", "Kasalxona", "Maktab", "Do'kon", "Bank", None, "medium"),
        ("지하철", "jihacheol", "Metro", "Avtobus", "Taksi", "Poezd", None, "medium"),
        ("수업", "sueop", "Dars", "Imtihon", "Kitob", "Uyga vazifa", None, "medium"),
        ("빠르다", "ppareuda", "Tez", "Sekin", "Baland", "Past", None, "hard"),
        ("복잡하다", "bokjaaphada", "Murakkab", "Oddiy", "Qiyin", "Oson", None, "hard"),
        ("그리워하다", "geuriwohada", "Sog'inmoq", "Yoqtirmoq", "Sevmoq", "Unutmoq", None, "hard"),
        ("사과", "sagwa", "Olma", "Nok", "Uzum", "Limon", None, "easy"),
        ("집", "jip", "Uy", "Ko'cha", "Bog'", "Mashina", None, "easy"),
        ("차", "cha", "Mashina", "Uy", "Kitob", "Qalam", None, "easy"),
        ("좋다", "jota", "Yaxshi", "Yomon", "Katta", "Kichik", None, "easy"),
        ("크다", "keuda", "Katta", "Kichik", "Baland", "Past", None, "easy"),
    ]
    await db.executemany(
        "INSERT INTO words (korean, romanization, translation, wrong1, wrong2, wrong3, wrong4, difficulty) "
        "VALUES (?,?,?,?,?,?,?,?)",
        sample_words,
    )
    await db.commit()


# ─── DB HELPERS ──────────────────────────────────────────────────────────────

async def get_user(user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None


async def ensure_user(user_id: int, username: str, full_name: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?,?,?)",
            (user_id, username, full_name),
        )
        await db.execute(
            "UPDATE users SET username=?, full_name=? WHERE user_id=?",
            (username, full_name, user_id),
        )
        await db.commit()


async def update_score(user_id: int, delta: int, correct: bool) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT streak, max_streak, lives FROM users WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return 0
        streak = row["streak"]
        max_streak = row["max_streak"]
        lives = row["lives"]
        if correct:
            streak += 1
            max_streak = max(max_streak, streak)
            multiplier = min(streak, 5)
            actual_delta = delta * multiplier
            await db.execute(
                "UPDATE users SET score=score+?, streak=?, max_streak=?, wins=wins+1 WHERE user_id=?",
                (actual_delta, streak, max_streak, user_id),
            )
        else:
            lives = max(0, lives - 1)
            await db.execute(
                "UPDATE users SET score=MAX(0, score+?), streak=0, lives=?, losses=losses+1 WHERE user_id=?",
                (delta, lives, user_id),
            )
        await db.commit()
        return streak if correct else 0


async def claim_daily_bonus(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT last_daily FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
        today = str(date.today())
        if row and row["last_daily"] == today:
            return 0
        bonus = 50
        await db.execute(
            "UPDATE users SET score=score+?, last_daily=? WHERE user_id=?",
            (bonus, today, user_id),
        )
        await db.commit()
        return bonus


def _get_fallback_wrongs(correct_translation: str) -> list[str]:
    fallback_pool = [
        "Uy", "Maktab", "Suv", "Non", "Kitob", "Do'kon", "Mashina",
        "Dengiz", "Osmon", "Tog'", "Daryo", "Mushuk", "It", "Qush",
        "Musiqa", "Rasm", "Sayohat", "Ovqat", "Kiyim", "Bank",
        "Dars", "Imtihon", "Bozor", "Metro", "Poezd", "Sport",
        "Baxtli", "Yaxshi", "Katta", "Tez", "Chiroyli", "Mazali",
    ]
    pool = [w for w in fallback_pool if w.lower() != correct_translation.lower()]
    return random.sample(pool, min(3, len(pool)))


async def get_random_question(difficulty: str = "easy") -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM words WHERE difficulty=? ORDER BY RANDOM() LIMIT 1", (difficulty,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            async with db.execute("SELECT * FROM words ORDER BY RANDOM() LIMIT 1") as cur:
                row = await cur.fetchone()
        if not row:
            return None
        row_dict = dict(row)
        correct = row_dict["translation"]
        wrongs = []
        for field in ["wrong1", "wrong2", "wrong3", "wrong4"]:
            val = row_dict.get(field)
            if val and str(val).strip() and str(val).strip() not in ("None", "???", "????"):
                wrongs.append(str(val).strip())
        if len(wrongs) < 3:
            fallbacks = _get_fallback_wrongs(correct)
            for fb in fallbacks:
                if fb not in wrongs and fb != correct:
                    wrongs.append(fb)
        selected_wrongs = random.sample(wrongs, min(3, len(wrongs)))
        options = [correct] + selected_wrongs
        random.shuffle(options)
        return {
            "id": row_dict["id"],
            "korean": row_dict["korean"],
            "romanization": row_dict.get("romanization", ""),
            "translation": correct,
            "options": options,
        }


async def get_random_word_for_typing(difficulty: str = "easy") -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM words WHERE difficulty=? ORDER BY RANDOM() LIMIT 1", (difficulty,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            async with db.execute("SELECT * FROM words ORDER BY RANDOM() LIMIT 1") as cur:
                row = await cur.fetchone()
        if not row:
            return None
        row_dict = dict(row)
        return {
            "id": row_dict["id"],
            "korean": row_dict["korean"],
            "romanization": row_dict.get("romanization", ""),
            "translation": row_dict["translation"],
        }


async def get_leaderboard() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id, username, full_name, score, wins, losses, badges "
            "FROM users ORDER BY score DESC LIMIT 10"
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_user_rank(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*)+1 FROM users WHERE score > (SELECT score FROM users WHERE user_id=?)",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0


async def award_badge(user_id: int, badge: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT badges FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return
        badges = row["badges"] or ""
        if badge not in badges:
            new_badges = (badges + "," + badge).strip(",")
            await db.execute("UPDATE users SET badges=? WHERE user_id=?", (new_badges, user_id))
            await db.commit()


async def check_and_award_badges(user_id: int) -> list:
    user = await get_user(user_id)
    if not user:
        return []
    earned = []
    rank = await get_user_rank(user_id)
    existing = user.get("badges", "") or ""
    if user["wins"] >= 1 and "Beginner" not in existing:
        await award_badge(user_id, "Beginner 🌱")
        earned.append("Beginner 🌱")
    if user["score"] >= 500 and "Korean Master" not in existing:
        await award_badge(user_id, "Korean Master 🏅")
        earned.append("Korean Master 🏅")
    if rank <= 10 and "Top 10 Player" not in existing:
        await award_badge(user_id, "Top 10 Player 🏆")
        earned.append("Top 10 Player 🏆")
    if user.get("max_streak", 0) >= 10 and "Streak King" not in existing:
        await award_badge(user_id, "Streak King 🔥")
        earned.append("Streak King 🔥")
    return earned


def auto_assign_difficulty(index: int) -> str:
    return ["easy", "medium", "hard"][index % 3]


async def rebalance_difficulties() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id FROM words ORDER BY id") as cur:
            all_words = [r[0] for r in await cur.fetchall()]
        counts = {"easy": 0, "medium": 0, "hard": 0}
        for idx, word_id in enumerate(all_words):
            diff = auto_assign_difficulty(idx)
            await db.execute("UPDATE words SET difficulty=? WHERE id=?", (diff, word_id))
            counts[diff] += 1
        await db.commit()
    return counts


# ─── 🧹 TO'LIQ TOZALASH ───────────────────────────────────────────────────────

async def full_cleanup_words() -> dict:
    result = {"duplicates_removed": 0, "wrongs_fixed": 0}

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("""
            SELECT MIN(id) as keep_id, korean, translation, COUNT(*) as cnt
            FROM words
            GROUP BY korean, translation
            HAVING cnt > 1
        """) as cur:
            dup_groups = [dict(r) for r in await cur.fetchall()]

        for group in dup_groups:
            async with db.execute(
                "SELECT id FROM words WHERE korean=? AND translation=? AND id!=?",
                (group["korean"], group["translation"], group["keep_id"])
            ) as cur:
                to_delete = [r[0] for r in await cur.fetchall()]
            for del_id in to_delete:
                await db.execute("DELETE FROM words WHERE id=?", (del_id,))
                result["duplicates_removed"] += 1

        async with db.execute("SELECT * FROM words") as cur:
            all_words = [dict(r) for r in await cur.fetchall()]

        for word in all_words:
            need_fix = False
            w1 = word.get("wrong1", "") or ""
            w2 = word.get("wrong2", "") or ""
            correct = word.get("translation", "")

            if not w1.strip() or w1.strip() in ("None", "???", "????"):
                fallbacks = _get_fallback_wrongs(correct)
                w1 = fallbacks[0] if fallbacks else "Boshqa ma'no"
                need_fix = True

            if not w2.strip() or w2.strip() in ("None", "???", "????") or w2 == w1:
                fallbacks = _get_fallback_wrongs(correct)
                fallbacks = [f for f in fallbacks if f != w1]
                w2 = fallbacks[0] if fallbacks else "Yana bir ma'no"
                need_fix = True

            if need_fix:
                await db.execute(
                    "UPDATE words SET wrong1=?, wrong2=? WHERE id=?",
                    (w1, w2, word["id"])
                )
                result["wrongs_fixed"] += 1

        await db.commit()

    return result


# ─── 🌐 TARJIMA FUNKSIYASI (YAXSHILANGAN) ─────────────────────────────────────

async def google_translate_free(text: str, src: str = "auto", dest: str = "uz") -> Optional[str]:
    """Google Translate bepul API (token kerak emas)"""
    try:
        encoded = urllib.parse.quote(text)
        url = (
            f"https://translate.googleapis.com/translate_a/single"
            f"?client=gtx&sl={src}&tl={dest}&dt=t&q={encoded}"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and data[0]:
                        result = "".join(
                            item[0] for item in data[0] if item and item[0]
                        )
                        return result.strip()
    except Exception as e:
        logger.warning(f"Google Translate xato: {e}")
    return None


def detect_language(text: str) -> str:
    """Matnning tilini aniqlash (oddiy usul)"""
    korean_chars = sum(1 for c in text if '\uAC00' <= c <= '\uD7A3' or '\u1100' <= c <= '\u11FF' or '\u3130' <= c <= '\u318F')
    if korean_chars > 0:
        return "korean"
    return "uzbek"


async def translate_text(text: str) -> dict:
    """
    Avval DB dan qidiradi, topilmasa Google Translate ishlatadi.
    UZ→KR va KR→UZ ikki tomonga ishlaydi.
    """
    text_clean = text.strip()
    text_lower = text_clean.lower()
    results = []

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # 1) Koreyscha so'z yoki romanizatsiya bilan qidirish
        async with db.execute(
            "SELECT * FROM words WHERE LOWER(korean)=? OR LOWER(romanization)=?",
            (text_lower, text_lower)
        ) as cur:
            kr_results = [dict(r) for r in await cur.fetchall()]

        if kr_results:
            for r in kr_results:
                results.append({
                    "direction": "kr_uz",
                    "input": r["korean"],
                    "output": r["translation"],
                    "romanization": r.get("romanization", ""),
                    "difficulty": r.get("difficulty", "easy"),
                    "source": "db",
                })
            return {"found": True, "direction": "kr_uz", "results": results}

        # 2) O'zbekcha tarjima bilan qidirish
        async with db.execute(
            "SELECT * FROM words WHERE LOWER(translation)=?",
            (text_lower,)
        ) as cur:
            uz_results = [dict(r) for r in await cur.fetchall()]

        if not uz_results:
            # Qisman moslik
            async with db.execute(
                "SELECT * FROM words WHERE LOWER(translation) LIKE ? OR LOWER(korean) LIKE ?",
                (f"%{text_lower}%", f"%{text_lower}%")
            ) as cur:
                uz_results = [dict(r) for r in await cur.fetchall()]

        if uz_results:
            for r in uz_results[:5]:
                results.append({
                    "direction": "uz_kr",
                    "input": r["translation"],
                    "output": r["korean"],
                    "romanization": r.get("romanization", ""),
                    "difficulty": r.get("difficulty", "easy"),
                    "source": "db",
                })
            return {"found": True, "direction": "uz_kr", "results": results}

    # 3) DB da topilmadi → Google Translate ishlatamiz
    lang = detect_language(text_clean)

    if lang == "korean":
        # Koreyscha → O'zbekcha
        translated = await google_translate_free(text_clean, src="ko", dest="uz")
        if translated:
            results.append({
                "direction": "kr_uz",
                "input": text_clean,
                "output": translated,
                "romanization": "",
                "difficulty": None,
                "source": "google",
            })
            return {"found": True, "direction": "kr_uz", "results": results}
    else:
        # O'zbekcha → Koreyscha
        translated_kr = await google_translate_free(text_clean, src="uz", dest="ko")
        if translated_kr:
            results.append({
                "direction": "uz_kr",
                "input": text_clean,
                "output": translated_kr,
                "romanization": "",
                "difficulty": None,
                "source": "google",
            })
            return {"found": True, "direction": "uz_kr", "results": results}

        # O'zbekcha aniqlanmagan bo'lsa, har ikki tomonga uruntir
        translated_kr2 = await google_translate_free(text_clean, src="auto", dest="ko")
        if translated_kr2:
            results.append({
                "direction": "uz_kr",
                "input": text_clean,
                "output": translated_kr2,
                "romanization": "",
                "difficulty": None,
                "source": "google",
            })
            return {"found": True, "direction": "uz_kr", "results": results}

    return {"found": False, "direction": None, "results": []}


# ─── PDF IMPORT ───────────────────────────────────────────────────────────────

async def import_words_from_pdf(file_path: str) -> tuple[int, list[str]]:
    try:
        import pdfplumber
    except ImportError:
        try:
            import subprocess
            subprocess.run(["pip", "install", "pdfplumber", "--break-system-packages", "-q"],
                           capture_output=True, text=True)
            import pdfplumber
        except Exception as e:
            return 0, [f"pdfplumber o'rnatilmadi: {e}"]

    imported = 0
    errors: list[str] = []

    try:
        with pdfplumber.open(file_path) as pdf:
            all_lines: list[str] = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    all_lines.extend(text.split('\n'))

        if not all_lines:
            return 0, ["PDF da matn topilmadi yoki PDF skaner (rasm) formatida."]

        async with aiosqlite.connect(DB_PATH) as db:
            rows = list(await db.execute_fetchall("SELECT COUNT(*) FROM words"))
            base_count = rows[0][0]

        async with aiosqlite.connect(DB_PATH) as db:
            for line_num, line in enumerate(all_lines, 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '|' in line:
                    parts = [p.strip() for p in line.split('|')]
                elif '\t' in line:
                    parts = [p.strip() for p in line.split('\t')]
                else:
                    continue
                parts = [p for p in parts if p]
                if len(parts) < 4:
                    continue

                korean = parts[0]
                romanization = parts[1] if len(parts) > 1 else ""
                translation = parts[2] if len(parts) > 2 else ""
                wrong1_raw = parts[3] if len(parts) > 3 else ""
                wrong2_raw = parts[4] if len(parts) > 4 else ""
                wrong3 = parts[5] if len(parts) > 5 and parts[5] else None

                difficulty = None
                if len(parts) > 6 and parts[6].lower() in ("easy", "medium", "hard"):
                    difficulty = parts[6].lower()
                elif len(parts) > 5 and parts[5].lower() in ("easy", "medium", "hard"):
                    difficulty = parts[5].lower()
                    wrong3 = None
                if difficulty is None:
                    difficulty = auto_assign_difficulty(base_count + imported)

                if not wrong1_raw or wrong1_raw in ("???", "????", "None"):
                    fallbacks = _get_fallback_wrongs(translation)
                    wrong1_raw = fallbacks[0] if fallbacks else "Noma'lum"
                if not wrong2_raw or wrong2_raw in ("???", "????", "None") or wrong2_raw == wrong1_raw:
                    fallbacks = _get_fallback_wrongs(translation)
                    fallbacks = [f for f in fallbacks if f != wrong1_raw]
                    wrong2_raw = fallbacks[0] if fallbacks else "Boshqa"

                if not korean or not translation:
                    errors.append(f"Qator {line_num}: Bo'sh majburiy maydon")
                    continue

                async with db.execute(
                    "SELECT id FROM words WHERE korean=? AND translation=?",
                    (korean, translation)
                ) as cur:
                    existing = await cur.fetchone()
                if existing:
                    errors.append(f"'{korean}' allaqachon mavjud")
                    continue

                await db.execute(
                    "INSERT INTO words (korean, romanization, translation, wrong1, wrong2, wrong3, difficulty) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (korean, romanization, translation, wrong1_raw, wrong2_raw, wrong3, difficulty)
                )
                imported += 1
            await db.commit()
    except Exception as e:
        errors.append(f"Fayl o'qishda xato: {e}")

    return imported, errors


# ─── PDF EXPORT ───────────────────────────────────────────────────────────────

async def generate_words_pdf(output_path: str, difficulty: Optional[str] = None) -> bool:
    try:
        from fpdf import FPDF
        has_font = os.path.exists(FONT_OTF_PATH)

        class WordsPDF(FPDF):
            def header(self) -> None:
                if has_font:
                    self.set_font("NotoKR", size=16)
                else:
                    self.set_font("Helvetica", "B", 16)
                self.set_fill_color(41, 128, 185)
                self.set_text_color(255, 255, 255)
                self.cell(0, 12, "Korean So'zlar Ro'yxati",
                           new_x="LMARGIN", new_y="NEXT", align="C", fill=True)
                self.ln(4)
                self.set_text_color(0, 0, 0)

            def footer(self) -> None:
                self.set_y(-15)
                if has_font:
                    self.set_font("NotoKR", size=8)
                else:
                    self.set_font("Helvetica", "I", 8)
                self.set_text_color(128, 128, 128)
                self.cell(0, 10, f"Sahifa {self.page_no()}", align="C")

        pdf = WordsPDF()
        if has_font:
            pdf.add_font("NotoKR", fname=FONT_OTF_PATH)
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            if difficulty:
                query = "SELECT * FROM words WHERE difficulty=? ORDER BY difficulty, id"
                params: tuple = (difficulty,)
            else:
                query = "SELECT * FROM words ORDER BY difficulty, id"
                params = ()
            async with db.execute(query, params) as cur:
                words = [dict(r) for r in await cur.fetchall()]

        if not words:
            return False

        if has_font:
            pdf.set_font("NotoKR", size=11)
        else:
            pdf.set_font("Helvetica", size=11)

        diff_labels = {"easy": "Oson", "medium": "O'rta", "hard": "Qiyin"}
        current_diff = None

        for idx, word in enumerate(words):
            diff = word.get("difficulty", "easy")
            if diff != current_diff:
                current_diff = diff
                pdf.ln(3)
                diff_colors = {
                    "easy": (39, 174, 96),
                    "medium": (241, 196, 15),
                    "hard": (231, 76, 60),
                }
                r, g, b = diff_colors.get(diff, (100, 100, 100))
                pdf.set_fill_color(r, g, b)
                pdf.set_text_color(255, 255, 255)
                if has_font:
                    pdf.set_font("NotoKR", size=12)
                else:
                    pdf.set_font("Helvetica", "B", 12)
                label = diff_labels.get(diff, diff)
                pdf.cell(0, 9, f"  {label.upper()} DARAJA",
                          new_x="LMARGIN", new_y="NEXT", fill=True)
                pdf.set_text_color(0, 0, 0)
                pdf.ln(2)

            korean = word.get("korean", "")
            romanization = word.get("romanization", "")
            translation = word.get("translation", "")
            wrong1 = word.get("wrong1", "")
            wrong2 = word.get("wrong2", "")

            if idx % 2 == 0:
                pdf.set_fill_color(245, 248, 252)
            else:
                pdf.set_fill_color(255, 255, 255)

            if has_font:
                pdf.set_font("NotoKR", size=14)
            else:
                pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(41, 128, 185)
            pdf.cell(40, 9, korean, fill=True)

            if has_font:
                pdf.set_font("NotoKR", size=10)
            else:
                pdf.set_font("Helvetica", "I", 10)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(38, 9, f"({romanization})", fill=True)

            if has_font:
                pdf.set_font("NotoKR", size=11)
            else:
                pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(39, 174, 96)
            pdf.cell(45, 9, translation, fill=True)

            if has_font:
                pdf.set_font("NotoKR", size=10)
            else:
                pdf.set_font("Helvetica", size=10)
            pdf.set_text_color(150, 50, 50)
            pdf.cell(0, 9, f"{wrong1}, {wrong2}",
                      new_x="LMARGIN", new_y="NEXT", fill=True)

        pdf.ln(8)
        pdf.set_fill_color(52, 73, 94)
        pdf.set_text_color(255, 255, 255)
        if has_font:
            pdf.set_font("NotoKR", size=11)
        else:
            pdf.set_font("Helvetica", "B", 11)
        easy_c = sum(1 for w in words if w.get("difficulty") == "easy")
        med_c = sum(1 for w in words if w.get("difficulty") == "medium")
        hard_c = sum(1 for w in words if w.get("difficulty") == "hard")
        pdf.cell(0, 10,
                 f"  Jami: {len(words)}  |  Oson: {easy_c}  |  O'rta: {med_c}  |  Qiyin: {hard_c}",
                 new_x="LMARGIN", new_y="NEXT", fill=True)
        pdf.output(output_path)
        return True
    except Exception as e:
        logger.error(f"PDF yaratishda xato: {e}")
        return False


# ─── FSM STATES ──────────────────────────────────────────────────────────────

class AddWordStates(StatesGroup):
    korean = State()
    romanization = State()
    translation = State()
    wrong1 = State()
    wrong2 = State()
    wrong3 = State()
    difficulty = State()


class QuizStates(StatesGroup):
    playing = State()


class TypingGameStates(StatesGroup):
    playing = State()


class TranslateStates(StatesGroup):
    waiting_input = State()


class ImportPdfState(StatesGroup):
    waiting_file = State()


# ─── KEYBOARDS ───────────────────────────────────────────────────────────────

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎮 Quiz", callback_data="start_quiz"),
                InlineKeyboardButton(text="✍️ So'z Yozing", callback_data="start_typing"),
            ],
            [
                InlineKeyboardButton(text="🌐 Tarjima", callback_data="start_translate"),
                InlineKeyboardButton(text="🎭 Mafia O'yini", callback_data="mafia_menu"),
            ],
            [
                InlineKeyboardButton(text="⚔️ 1v1 Battle", callback_data="join_battle"),
                InlineKeyboardButton(text="👥 2v2 Jang", callback_data="team_battle_menu"),
            ],
            [
                InlineKeyboardButton(text="🏆 Reyting", callback_data="leaderboard"),
                InlineKeyboardButton(text="👤 Profil", callback_data="profile"),
            ],
            [
                InlineKeyboardButton(text="🎯 Qiyinchilik", callback_data="difficulty_menu"),
                InlineKeyboardButton(text="🎁 Kunlik bonus", callback_data="daily_bonus"),
            ],
        ]
    )


def quiz_options_kb(options: list, word_id: int) -> InlineKeyboardMarkup:
    letters = ["A", "B", "C", "D"]
    buttons = [
        [InlineKeyboardButton(
            text=f"{letters[i]}) {opt}",
            callback_data=f"ans:{word_id}:{opt[:30]}",
        )]
        for i, opt in enumerate(options[:4])
    ]
    buttons.append([InlineKeyboardButton(text="🚪 Quizdan chiqish", callback_data="quit_quiz")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def difficulty_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🟢 Oson", callback_data="set_diff:easy"),
                InlineKeyboardButton(text="🟡 O'rta", callback_data="set_diff:medium"),
                InlineKeyboardButton(text="🔴 Qiyin", callback_data="set_diff:hard"),
            ],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_menu")],
        ]
    )


def battle_options_kb(battle_id: int, options: list) -> InlineKeyboardMarkup:
    letters = ["A", "B", "C", "D"]
    buttons = [
        [InlineKeyboardButton(
            text=f"{letters[i]}) {opt}",
            callback_data=f"bans:{battle_id}:{opt[:30]}",
        )]
        for i, opt in enumerate(options[:4])
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def team_battle_answer_kb(battle_id: int, q_index: int, options: list) -> InlineKeyboardMarkup:
    letters = ["A", "B", "C", "D"]
    buttons = [
        [InlineKeyboardButton(
            text=f"{letters[i]}) {opt}",
            callback_data=f"tbans:{battle_id}:{q_index}:{opt[:28]}",
        )]
        for i, opt in enumerate(options[:4])
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def next_or_exit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➡️ Keyingi savol", callback_data="next_question"),
                InlineKeyboardButton(text="🚪 Chiqish", callback_data="quit_quiz"),
            ]
        ]
    )


def typing_next_or_exit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➡️ Keyingisi", callback_data="typing_next"),
                InlineKeyboardButton(text="🚪 Chiqish", callback_data="typing_quit"),
            ]
        ]
    )


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def streak_emoji(streak: int) -> str:
    if streak >= 5:
        return "🔥🔥🔥"
    if streak >= 3:
        return "🔥🔥"
    if streak >= 2:
        return "🔥"
    return ""


def difficulty_label(d: str) -> str:
    return {"easy": "🟢 Oson", "medium": "🟡 O'rta", "hard": "🔴 Qiyin"}.get(d, d)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def safe_message(msg: MaybeInaccessibleMessage) -> Optional[Message]:
    if isinstance(msg, Message):
        return msg
    return None


def normalize_answer(text: str) -> str:
    text = text.lower().strip()
    text = text.replace("'", "'").replace("`", "'").replace("ʻ", "'")
    text = text.replace("  ", " ")
    return text


active_quizzes: dict = {}
active_typing: dict = {}
router = Router()


# ─── /start ──────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext) -> None:
    """
    /start — oddiy ishga tushirish.
    /start mafia_{chat_id} — mafia lobby havolasidan kelganda
    """
    user = msg.from_user
    if not user:
        return
    await ensure_user(user.id, user.username or "", user.full_name or "")

    # Deep link orqali mafia lobbyga qo'shish
    args = msg.text.split(maxsplit=1)[1] if msg.text and len(msg.text.split()) > 1 else ""
    if args.startswith("mafia_"):
        try:
            chat_id_from_link = int(args.split("_")[1])
            lobby = mafia_lobbies.get(chat_id_from_link)
            if lobby and not lobby.get("started"):
                if user.id not in lobby["players"]:
                    if len(lobby["players"]) < MAFIA_MAX_PLAYERS:
                        lobby["players"].append(user.id)
                        lobby["player_names"][user.id] = user.full_name or f"Player{user.id}"
                        await msg.answer(
                            f"✅ <b>Mafia lobbyga qo'shildingiz!</b>\n\n"
                            f"👥 O'yinchilar: {len(lobby['players'])}/{MAFIA_MAX_PLAYERS}\n"
                            f"Lobby egasi o'yinni boshlaganida xabar olasiz.",
                            parse_mode=ParseMode.HTML,
                            reply_markup=main_menu_kb(),
                        )

                        # Lobby egasiga xabar berish
                        host_id = lobby["host"]
                        try:
                            bot = msg.bot
                            if bot:
                                player_names_list = "\n".join(
                                    f"{i+1}. {lobby['player_names'].get(uid, f'Player{uid}')}"
                                    for i, uid in enumerate(lobby["players"])
                                )
                                await bot.send_message(
                                    host_id,
                                    f"🎭 <b>{user.full_name}</b> lobbyga qo'shildi!\n\n"
                                    f"👥 O'yinchilar ({len(lobby['players'])}/{MAFIA_MAX_PLAYERS}):\n"
                                    f"{player_names_list}",
                                    parse_mode=ParseMode.HTML,
                                )
                        except Exception:
                            pass
                        return
                    else:
                        await msg.answer("❌ Lobby to'liq!", reply_markup=main_menu_kb())
                        return
                else:
                    await msg.answer(
                        "⚠️ Siz allaqachon bu lobbydasiz!",
                        reply_markup=main_menu_kb(),
                    )
                    return
            else:
                await msg.answer(
                    "❌ Bu lobby mavjud emas yoki o'yin boshlangan!",
                    reply_markup=main_menu_kb(),
                )
                return
        except (ValueError, IndexError):
            pass

    bonus = await claim_daily_bonus(user.id)
    bonus_text = f"\n🎁 <b>Kunlik bonus: +{bonus} ball!</b>" if bonus else ""
    text = (
        f"🇰🇷 <b>Korean Vocabulary Bot V3</b> ga xush kelibsiz!\n\n"
        f"👋 Salom, <b>{user.full_name}</b>!{bonus_text}\n\n"
        f"🆕 Yangi: 🌐 Tarjima (DB + Google), 🎭 Mafia O'yini, 🧹 Tozalash\n\n"
        f"Pastdagi tugmalardan birini tanlang 👇"
    )
    await msg.answer(text, reply_markup=main_menu_kb(), parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(cq: CallbackQuery) -> None:
    m = safe_message(cq.message) if cq.message else None
    if not m:
        await cq.answer()
        return
    await m.edit_text(
        "🏠 <b>Asosiy menyu</b>\n\nNimadan boshlaysiz?",
        reply_markup=main_menu_kb(),
        parse_mode=ParseMode.HTML,
    )


# ─── PROFIL ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "profile")
async def cb_profile(cq: CallbackQuery) -> None:
    user = await get_user(cq.from_user.id)
    if not user:
        await cq.answer("Avval /start ni bosing")
        return
    rank = await get_user_rank(cq.from_user.id)
    badges = user.get("badges", "") or "Hali yo'q"
    lives_str = "❤️" * user["lives"] + "🖤" * (3 - user["lives"])
    multiplier = min(user["streak"], 5)
    text = (
        f"👤 <b>Profilingiz</b>\n\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"📛 Ism: <b>{user['full_name']}</b>\n"
        f"⭐ Ball: <b>{user['score']}</b>\n"
        f"🏆 O'rin: #{rank}\n"
        f"✅ G'alabalar: {user['wins']}\n"
        f"❌ Mag'lubiyatlar: {user['losses']}\n"
        f"🔥 Streak: {user['streak']} (max: {user['max_streak']})\n"
        f"⚡ Multiplier: x{multiplier}\n"
        f"❤️ Jonlar: {lives_str}\n"
        f"🎯 Daraja: {difficulty_label(user['difficulty'])}\n"
        f"🏅 Nishonlar: {badges}\n"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❤️ Jonlarni tiklash (-50 ball)", callback_data="restore_lives")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_menu")],
        ]
    )
    m = safe_message(cq.message) if cq.message else None
    if not m:
        await cq.answer()
        return
    await m.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "restore_lives")
async def cb_restore_lives(cq: CallbackQuery) -> None:
    user = await get_user(cq.from_user.id)
    if not user:
        return
    if user["lives"] >= 3:
        await cq.answer("Jonlaringiz to'liq! ❤️❤️❤️")
        return
    if user["score"] < 50:
        await cq.answer("Kamida 50 ball kerak!")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET lives=3, score=score-50 WHERE user_id=?", (cq.from_user.id,)
        )
        await db.commit()
    await cq.answer("❤️ Jonlar tiklandi! -50 ball")
    await cb_profile(cq)


@router.callback_query(F.data == "daily_bonus")
async def cb_daily_bonus(cq: CallbackQuery) -> None:
    bonus = await claim_daily_bonus(cq.from_user.id)
    if bonus:
        await cq.answer(f"🎁 +{bonus} ball! Ertaga qaytib keling!", show_alert=True)
    else:
        await cq.answer("⏳ Kunlik bonus allaqachon olindi. Ertaga qaytib keling!", show_alert=True)


@router.callback_query(F.data == "difficulty_menu")
async def cb_difficulty_menu(cq: CallbackQuery) -> None:
    m = safe_message(cq.message) if cq.message else None
    if not m:
        await cq.answer()
        return
    await m.edit_text(
        "🎯 <b>Qiyinchilik darajasini tanlang:</b>",
        reply_markup=difficulty_kb(),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("set_diff:"))
async def cb_set_difficulty(cq: CallbackQuery) -> None:
    diff = (cq.data or "").split(":")[1]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET difficulty=? WHERE user_id=?", (diff, cq.from_user.id))
        await db.commit()
    await cq.answer(f"✅ Daraja: {difficulty_label(diff)}")
    await cb_main_menu(cq)


@router.callback_query(F.data == "leaderboard")
@router.message(Command("leaderboard"))
async def cb_leaderboard(update: Union[CallbackQuery, Message]) -> None:
    user_id = update.from_user.id if update.from_user else 0
    board = await get_leaderboard()
    rank = await get_user_rank(user_id)
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>TOP 10 O'YINCHILAR</b>\n"]
    for i, u in enumerate(board):
        medal = medals[i] if i < 3 else f"{i + 1}."
        name = u["full_name"] or u["username"] or f"User{u['user_id']}"
        lines.append(f"{medal} {name} — <b>{u['score']}</b> ball")
    lines.append(f"\n📍 Sizning o'rningiz: <b>#{rank}</b>")
    text = "\n".join(lines)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_menu")]]
    )
    if isinstance(update, CallbackQuery):
        m = safe_message(update.message) if update.message else None
        if not m:
            await update.answer()
            return
        await m.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await update.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# ─── 🌐 TARJIMA ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "start_translate")
async def cb_start_translate(cq: CallbackQuery, state: FSMContext) -> None:
    await ensure_user(cq.from_user.id, cq.from_user.username or "", cq.from_user.full_name or "")
    m = safe_message(cq.message) if cq.message else None
    if not m:
        return
    await m.edit_text(
        "🌐 <b>Tarjima</b>\n\n"
        "So'z yoki ibora yuboring:\n\n"
        "🇺🇿 → 🇰🇷  O'zbekcha yozsangiz, Koreyscha tarjima\n"
        "🇰🇷 → 🇺🇿  Koreyscha yozsangiz, O'zbekcha tarjima\n\n"
        "✅ Avval bazadan qidiradi\n"
        "🌍 Topilmasa Google Translate dan oladi\n\n"
        "Misol: <code>salom</code> yoki <code>안녕</code> yoki <code>안녕하세요</code>\n\n"
        "Chiqish uchun /cancel",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_menu")]
        ])
    )
    await state.set_state(TranslateStates.waiting_input)
    await cq.answer()


@router.message(Command("translate"), Command("tarjima"))
async def cmd_translate(msg: Message, state: FSMContext) -> None:
    await ensure_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.full_name or "")
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) > 1:
        await _do_translate(msg, parts[1])
        return
    await msg.answer(
        "🌐 <b>Tarjima</b>\n\n"
        "Tarjima qilmoqchi bo'lgan so'zni yuboring:\n"
        "🇺🇿 O'zbekcha yoki 🇰🇷 Koreyscha",
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(TranslateStates.waiting_input)


@router.message(TranslateStates.waiting_input)
async def handle_translate_input(msg: Message, state: FSMContext) -> None:
    text = (msg.text or "").strip()
    if not text:
        return
    await _do_translate(msg, text)


async def _do_translate(msg: Message, text: str) -> None:
    # Qidirish davomida "yuklanmoqda" ko'rsatish
    wait_msg = await msg.answer("🔍 Tarjima qilinmoqda...")

    result = await translate_text(text)

    try:
        await wait_msg.delete()
    except Exception:
        pass

    if not result["found"]:
        await msg.answer(
            f"🔍 <b>'{text}'</b> topilmadi.\n\n"
            f"Bu so'z bazada yo'q va tarjimasi topilmadi.\n"
            f"Admin /add_word bilan qo'shishi mumkin.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Bosh menyu", callback_data="main_menu")]
            ])
        )
        return

    direction = result["direction"]
    results = result["results"]

    lines = []

    if direction == "kr_uz":
        flag = "🇰🇷 → 🇺🇿"
        lines.append(f"🌐 <b>Tarjima: {flag}</b>\n")
        for r in results:
            source_icon = "📚" if r.get("source") == "db" else "🌍"
            diff = r.get("difficulty")
            diff_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(diff or "", "")
            rom = f"  <i>({r['romanization']})</i>" if r.get("romanization") else ""
            lines.append(
                f"🇰🇷 <b>{r['input']}</b>{rom}\n"
                f"🇺🇿 {r['output']}  {diff_emoji} {source_icon}\n"
            )
    else:
        flag = "🇺🇿 → 🇰🇷"
        lines.append(f"🌐 <b>Tarjima: {flag}</b>\n")
        for r in results:
            source_icon = "📚" if r.get("source") == "db" else "🌍"
            diff = r.get("difficulty")
            diff_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(diff or "", "")
            rom = f"  <i>({r['romanization']})</i>" if r.get("romanization") else ""
            lines.append(
                f"🇺🇿 <b>{r['input']}</b>\n"
                f"🇰🇷 {r['output']}{rom}  {diff_emoji} {source_icon}\n"
            )

    lines.append("📚 = Bazadan  🌍 = Google Translate")
    lines.append("\n📝 Yana so'z yuboring yoki /cancel")

    await msg.answer(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Bosh menyu", callback_data="main_menu")]
        ])
    )


# ==================== 🎭 MAFIA O'YINI ====================

mafia_router = Router()


async def get_mafia_invite_link(bot: Bot, chat_id: int) -> str:
    """
    Mafia lobbyga taklif havolasini yaratadi.
    
    - Guruh uchun: Bot username orqali deep link (t.me/BotUsername?start=mafia_{chat_id})
    - Shaxsiy chat uchun: Faqat bot linki
    """
    try:
        bot_info = await bot.get_me()
        bot_username = bot_info.username
        # Deep link: /start mafia_{chat_id} parametri bilan
        deep_link = f"https://t.me/{bot_username}?start=mafia_{chat_id}"
        return deep_link
    except Exception as e:
        logger.error(f"Invite link xato: {e}")
        return "Bot havolasini olib bo'lmadi"


@mafia_router.callback_query(F.data == "mafia_menu")
async def mafia_menu(cq: CallbackQuery, bot: Bot) -> None:
    m = safe_message(cq.message)
    if not m:
        await cq.answer()
        return

    chat_id = m.chat.id
    lobby = mafia_lobbies.get(chat_id)

    if lobby and not lobby.get("started"):
        player_count = len(lobby["players"])
        player_names = lobby.get("player_names", {})
        names_list = "\n".join(
            f"{i+1}. {player_names.get(uid, f'Player{uid}')}"
            for i, uid in enumerate(lobby["players"])
        )

        # Taklif havolasini olish
        invite_link = await get_mafia_invite_link(bot, chat_id)

        text = (
            f"🎭 <b>Mafia Lobby</b>\n\n"
            f"👥 O'yinchilar: {player_count}/{MAFIA_MAX_PLAYERS}\n\n"
            f"{names_list}\n\n"
            f"🎯 Kerak: kamida {MAFIA_MIN_PLAYERS} kishi\n\n"
            f"📎 <b>Lobbyga taklif havolasi:</b>\n"
            f"<code>{invite_link}</code>\n\n"
            f"👆 Havolani do'stlaringizga yuboring — ular botga /start bosishsa avtomatik qo'shiladi!"
        )

        kb_rows = []

        # Lobbyga qo'shilish tugmasi (URL button bilan!)
        kb_rows.append([
            InlineKeyboardButton(
                text="✅ Lobbyga qo'shil",
                callback_data="mafia_join"
            )
        ])

        # Host uchun boshlash tugmasi
        if lobby.get("host") == cq.from_user.id and player_count >= MAFIA_MIN_PLAYERS:
            kb_rows.append([
                InlineKeyboardButton(text="▶️ O'yinni boshlash", callback_data="mafia_start")
            ])

        # Havolani yuborish (URL inline button)
        kb_rows.append([
            InlineKeyboardButton(
                text="📤 Havolani ulashish",
                url=invite_link
            )
        ])

        kb_rows.append([
            InlineKeyboardButton(text="🔄 Yangilash", callback_data="mafia_menu")
        ])
        kb_rows.append([
            InlineKeyboardButton(text="🚪 Lobbydan chiqish", callback_data="mafia_leave")
        ])
        kb_rows.append([
            InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_menu")
        ])

        await m.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
            parse_mode=ParseMode.HTML
        )
    else:
        text = (
            "🎭 <b>Mafia O'yini</b>\n\n"
            "Klassik Mafia o'yini Telegram botda!\n\n"
            "👥 4-6 kishi\n"
            "🔴 Don (Bosh Mafia)\n"
            "🔴 Mafia\n"
            "💚 Shifokor\n"
            "🔵 Detektiv\n"
            "⚪ Fuqarolar\n\n"
            "📌 <b>Qanday o'ynash:</b>\n"
            "1. Lobby yarating\n"
            "2. Taklif havolasini do'stlaringizga yuboring\n"
            "3. 4+ kishi bo'lgach boshlang\n\n"
            "💡 Do'stlar havola orqali botga /start bossalar — avtomatik lobbyga qo'shiladi!"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎭 Lobby yaratish", callback_data="mafia_create")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_menu")],
        ])
        await m.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

    await cq.answer()


@mafia_router.callback_query(F.data == "mafia_create")
async def mafia_create(cq: CallbackQuery, bot: Bot) -> None:
    m = safe_message(cq.message)
    if not m:
        await cq.answer()
        return

    chat_id = m.chat.id
    user_id = cq.from_user.id

    if chat_id in mafia_lobbies and not mafia_lobbies[chat_id].get("started", False):
        await cq.answer("⚠️ Allaqachon lobby mavjud!", show_alert=True)
        return

    mafia_lobbies[chat_id] = {
        "host": user_id,
        "players": [user_id],
        "player_names": {user_id: cq.from_user.full_name or f"Player{user_id}"},
        "started": False,
        "created_at": time.time(),
    }

    await cq.answer("✅ Lobby yaratildi!")
    await mafia_menu(cq, bot)


@mafia_router.callback_query(F.data == "mafia_join")
async def mafia_join(cq: CallbackQuery, bot: Bot) -> None:
    m = safe_message(cq.message)
    if not m:
        await cq.answer()
        return

    chat_id = m.chat.id
    user_id = cq.from_user.id

    lobby = mafia_lobbies.get(chat_id)
    if not lobby:
        await cq.answer("❌ Lobby topilmadi!", show_alert=True)
        return

    if lobby.get("started"):
        await cq.answer("❌ O'yin boshlangan!", show_alert=True)
        return

    if user_id in lobby["players"]:
        await cq.answer("⚠️ Siz lobbydasiz!", show_alert=True)
        return

    if len(lobby["players"]) >= MAFIA_MAX_PLAYERS:
        await cq.answer(f"❌ Lobby to'liq! (max {MAFIA_MAX_PLAYERS})", show_alert=True)
        return

    lobby["players"].append(user_id)
    lobby["player_names"][user_id] = cq.from_user.full_name or f"Player{user_id}"

    await cq.answer("✅ Lobbyga qo'shildingiz!")
    await mafia_menu(cq, bot)


@mafia_router.callback_query(F.data == "mafia_leave")
async def mafia_leave(cq: CallbackQuery) -> None:
    m = safe_message(cq.message)
    if not m:
        await cq.answer()
        return

    chat_id = m.chat.id
    user_id = cq.from_user.id
    lobby = mafia_lobbies.get(chat_id)

    if not lobby:
        await cq.answer("❌ Lobby yo'q!")
        return

    if user_id in lobby["players"]:
        lobby["players"].remove(user_id)
        lobby["player_names"].pop(user_id, None)

    if not lobby["players"] or lobby["host"] == user_id:
        mafia_lobbies.pop(chat_id, None)
        await cq.answer("🚪 Lobby yopildi.")
        await cb_main_menu(cq)
        return

    await cq.answer("🚪 Lobbydan chiqdingiz.")
    await mafia_menu(cq, cq.bot)


@mafia_router.callback_query(F.data == "mafia_start")
async def mafia_start(cq: CallbackQuery, bot: Bot) -> None:
    m = safe_message(cq.message)
    if not m:
        await cq.answer()
        return

    chat_id = m.chat.id
    user_id = cq.from_user.id
    lobby = mafia_lobbies.get(chat_id)

    if not lobby:
        await cq.answer("❌ Lobby topilmadi!")
        return

    if lobby["host"] != user_id:
        await cq.answer("❌ Faqat lobby yaratuvchi boshlaydi!")
        return

    players = lobby["players"]
    if len(players) < MAFIA_MIN_PLAYERS:
        await cq.answer(f"❌ Kamida {MAFIA_MIN_PLAYERS} kishi kerak!", show_alert=True)
        return

    # Rollarni taqsimlash
    player_count = min(len(players), MAFIA_MAX_PLAYERS)
    players = players[:player_count]
    role_config = MAFIA_ROLES.get(player_count, MAFIA_ROLES[MAFIA_MAX_PLAYERS])

    role_list = []
    for role, count in role_config.items():
        role_list.extend([role] * count)

    while len(role_list) < player_count:
        role_list.append("citizen")

    random.shuffle(role_list)
    assigned_roles = dict(zip(players, role_list))

    lobby["started"] = True
    mafia_games[chat_id] = {
        "roles": assigned_roles,
        "alive": list(players),
        "player_names": lobby["player_names"],
        "phase": "night",
        "round": 1,
        "night_actions": {},
        "votes": {},
        "doctor_save": None,
        "detective_check": None,
        "mafia_kill": None,
        "chat_id": chat_id,
    }

    await m.edit_text(
        f"🎭 <b>Mafia O'yini boshlanmoqda!</b>\n\n"
        f"👥 O'yinchilar: {player_count} kishi\n"
        f"📨 Rolingiz shaxsiy xabarda yuborildi!\n\n"
        f"🌙 1-kecha boshlanmoqda...",
        parse_mode=ParseMode.HTML,
    )

    # Rollarni shaxsiy xabarda yuborish
    for uid, role in assigned_roles.items():
        role_name = MAFIA_ROLE_NAMES.get(role, role)
        role_info = MAFIA_ROLE_INFO.get(role, "")

        extra_info = ""
        if role in ["mafia", "don"]:
            team = [
                lobby["player_names"].get(uid2, f"Player{uid2}")
                for uid2 in players
                if uid2 != uid and assigned_roles.get(uid2) in ["mafia", "don"]
            ]
            if team:
                extra_info = f"\n\n👥 Mafia jamoasi: {', '.join(team)}"

        try:
            await bot.send_message(
                uid,
                f"🎭 <b>Mafia O'yini</b>\n\n"
                f"⭐ Rolingiz: <b>{role_name}</b>\n\n"
                f"ℹ️ {role_info}{extra_info}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    await asyncio.sleep(2)
    await mafia_night_phase(bot, chat_id)


async def mafia_night_phase(bot: Bot, chat_id: int) -> None:
    game = mafia_games.get(chat_id)
    if not game:
        return

    game["phase"] = "night"
    game["mafia_kill"] = None
    game["doctor_save"] = None

    round_num = game["round"]
    alive = game["alive"]
    roles = game["roles"]
    player_names = game["player_names"]

    await bot.send_message(
        chat_id,
        f"🌙 <b>Kecha #{round_num}</b>\n\n😴 Shahar uxlab qoldi...\n\nMafia, Shifokor harakat qiling!",
        parse_mode=ParseMode.HTML,
    )

    # Mafia uchun nishon tanlash
    for uid, role in roles.items():
        if uid not in alive:
            continue
        if role in ("don", "mafia"):
            targets = [u for u in alive if roles.get(u) not in ("don", "mafia")]
            if targets:
                buttons = [
                    [InlineKeyboardButton(
                        text=f"🔪 {player_names.get(t, f'Player{t}')}",
                        callback_data=f"mk:{chat_id}:{t}"
                    )]
                    for t in targets
                ]
                try:
                    await bot.send_message(
                        uid,
                        f"🌙 <b>Kecha #{round_num}</b>\nKimni o'ldiramiz?",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass

    # Shifokor uchun saqlash
    for uid, role in roles.items():
        if uid not in alive:
            continue
        if role == "doctor":
            buttons = [
                [InlineKeyboardButton(
                    text=f"💚 {player_names.get(t, f'Player{t}')}",
                    callback_data=f"ms:{chat_id}:{t}"
                )]
                for t in alive
            ]
            try:
                await bot.send_message(
                    uid,
                    f"🌙 <b>Kecha #{round_num}</b>\nKimni saqlaymiz?",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass

    asyncio.create_task(mafia_night_timeout(bot, chat_id, round_num))


async def mafia_night_timeout(bot: Bot, chat_id: int, round_num: int) -> None:
    await asyncio.sleep(45)
    game = mafia_games.get(chat_id)
    if game and game.get("round") == round_num and game.get("phase") == "night":
        await mafia_process_night(bot, chat_id)


@mafia_router.callback_query(F.data.startswith("mk:"))
async def mafia_kill(cq: CallbackQuery, bot: Bot) -> None:
    parts = (cq.data or "").split(":")
    if len(parts) < 3:
        return
    chat_id = int(parts[1])
    target = int(parts[2])
    game = mafia_games.get(chat_id)
    if game and game.get("phase") == "night":
        game["mafia_kill"] = target
        await cq.answer("✅ Nishon tanlandi!")
        await mafia_process_night(bot, chat_id)


@mafia_router.callback_query(F.data.startswith("ms:"))
async def mafia_save(cq: CallbackQuery, bot: Bot) -> None:
    parts = (cq.data or "").split(":")
    if len(parts) < 3:
        return
    chat_id = int(parts[1])
    target = int(parts[2])
    game = mafia_games.get(chat_id)
    if game and game.get("phase") == "night":
        game["doctor_save"] = target
        await cq.answer("✅ Saqlandi!")


async def mafia_process_night(bot: Bot, chat_id: int) -> None:
    game = mafia_games.get(chat_id)
    if not game or game.get("phase") != "night":
        return

    game["phase"] = "day"
    kill = game.get("mafia_kill")
    save = game.get("doctor_save")
    alive = game["alive"]
    player_names = game["player_names"]

    killed = None
    if kill and kill != save and kill in alive:
        alive.remove(kill)
        killed = kill

    roles = game["roles"]
    mafia_count = sum(1 for u in alive if roles.get(u) in ("don", "mafia"))
    citizen_count = len(alive) - mafia_count

    if mafia_count == 0:
        await bot.send_message(chat_id, "🎉 <b>FUQAROLAR G'ALABA QOZONDI!</b> 🎉", parse_mode=ParseMode.HTML)
        mafia_lobbies.pop(chat_id, None)
        mafia_games.pop(chat_id, None)
        return
    elif mafia_count >= citizen_count:
        await bot.send_message(chat_id, "🔴 <b>MAFIA G'ALABA QOZONDI!</b> 🔴", parse_mode=ParseMode.HTML)
        mafia_lobbies.pop(chat_id, None)
        mafia_games.pop(chat_id, None)
        return

    if killed:
        killed_name = player_names.get(killed, "Noma'lum")
        await bot.send_message(
            chat_id,
            f"☀️ <b>Tong</b>\n\n💀 <b>{killed_name}</b> o'ldirildi!",
            parse_mode=ParseMode.HTML
        )
    else:
        await bot.send_message(
            chat_id,
            f"☀️ <b>Tong</b>\n\n✅ Kechasi hech kim o'lmadi!",
            parse_mode=ParseMode.HTML
        )

    alive = game["alive"]
    if len(alive) <= 1:
        await bot.send_message(chat_id, "🎭 O'yin tugadi!")
        mafia_lobbies.pop(chat_id, None)
        mafia_games.pop(chat_id, None)
        return

    vote_buttons = [
        [InlineKeyboardButton(
            text=player_names.get(u, f"Player{u}"),
            callback_data=f"mv:{chat_id}:{u}"
        )]
        for u in alive
    ]
    game["votes"] = {}
    game["phase"] = "vote"

    await bot.send_message(
        chat_id,
        f"🗳️ <b>Ovoz berish vaqti!</b>\n\nKimni chiqarib tashlaymiz?\n⏱️ 45 soniya!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=vote_buttons),
        parse_mode=ParseMode.HTML,
    )
    asyncio.create_task(mafia_vote_timeout(bot, chat_id))


@mafia_router.callback_query(F.data.startswith("mv:"))
async def mafia_vote(cq: CallbackQuery, bot: Bot) -> None:
    parts = (cq.data or "").split(":")
    if len(parts) < 3:
        return
    chat_id = int(parts[1])
    target = int(parts[2])
    user_id = cq.from_user.id

    game = mafia_games.get(chat_id)
    if not game or game.get("phase") != "vote":
        await cq.answer("Ovoz berish vaqti emas!")
        return
    if user_id not in game["alive"]:
        await cq.answer("Siz o'liksiz, ovoz bera olmaysiz!")
        return
    if user_id in game["votes"]:
        await cq.answer("Siz allaqachon ovoz bergansiz!")
        return

    game["votes"][user_id] = target
    target_name = game["player_names"].get(target, f"Player{target}")
    await cq.answer(f"✅ {target_name} ga ovoz berildi!")

    if len(game["votes"]) >= len(game["alive"]):
        await mafia_process_vote(bot, chat_id)


async def mafia_vote_timeout(bot: Bot, chat_id: int) -> None:
    await asyncio.sleep(45)
    game = mafia_games.get(chat_id)
    if game and game.get("phase") == "vote":
        await mafia_process_vote(bot, chat_id)


async def mafia_process_vote(bot: Bot, chat_id: int) -> None:
    game = mafia_games.get(chat_id)
    if not game or game.get("phase") != "vote":
        return

    votes = game["votes"]
    alive = game["alive"]
    player_names = game["player_names"]

    if votes:
        vote_count: dict = {}
        for v, t in votes.items():
            vote_count[t] = vote_count.get(t, 0) + 1

        max_votes = max(vote_count.values())
        eliminated = [u for u, c in vote_count.items() if c == max_votes]

        if len(eliminated) == 1:
            dead = eliminated[0]
            dead_name = player_names.get(dead, "Noma'lum")
            if dead in alive:
                alive.remove(dead)
            await bot.send_message(
                chat_id,
                f"🗳️ <b>{dead_name}</b> ({max_votes} ovoz bilan) chiqarib tashlandi!",
                parse_mode=ParseMode.HTML
            )
        else:
            await bot.send_message(
                chat_id,
                "🗳️ Ovozlar teng taqsimlandi! Hech kim chiqarilmadi.",
                parse_mode=ParseMode.HTML
            )
    else:
        await bot.send_message(chat_id, "🗳️ Hech kim ovoz bermadi.")

    # G'alaba tekshiruvi
    roles = game["roles"]
    mafia_count = sum(1 for u in alive if roles.get(u) in ("don", "mafia"))
    citizen_count = len(alive) - mafia_count

    if mafia_count == 0:
        await bot.send_message(chat_id, "🎉 <b>FUQAROLAR G'ALABA QOZONDI!</b> 🎉", parse_mode=ParseMode.HTML)
        mafia_lobbies.pop(chat_id, None)
        mafia_games.pop(chat_id, None)
        return
    elif mafia_count >= citizen_count:
        await bot.send_message(chat_id, "🔴 <b>MAFIA G'ALABA QOZONDI!</b> 🔴", parse_mode=ParseMode.HTML)
        mafia_lobbies.pop(chat_id, None)
        mafia_games.pop(chat_id, None)
        return

    if len(alive) <= 1:
        await bot.send_message(chat_id, "🎭 O'yin tugadi!")
        mafia_lobbies.pop(chat_id, None)
        mafia_games.pop(chat_id, None)
        return

    game["round"] += 1
    game["phase"] = "night"
    game["mafia_kill"] = None
    game["doctor_save"] = None
    game["votes"] = {}

    await asyncio.sleep(2)
    await mafia_night_phase(bot, chat_id)


# ─── QUIZ ─────────────────────────────────────────────────────────────────────

async def send_question(bot: Bot, user_id: int, chat_id: int, state: FSMContext) -> None:
    user = await get_user(user_id)
    if not user:
        return
    if user["lives"] <= 0:
        await bot.send_message(
            chat_id,
            "💀 <b>Jonlaringiz tugadi!</b>\nQaytadan boshlash uchun jonlarni tiklang.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❤️ Jonlarni tiklash", callback_data="restore_lives")],
                [InlineKeyboardButton(text="🏠 Bosh menu", callback_data="main_menu")],
            ]),
            parse_mode=ParseMode.HTML,
        )
        await state.clear()
        return
    q = await get_random_question(user["difficulty"])
    if not q:
        await bot.send_message(chat_id, "❌ So'zlar topilmadi.")
        await state.clear()
        return
    streak = user["streak"]
    multiplier = min(streak, 5)
    lives_str = "❤️" * user["lives"] + "🖤" * (3 - user["lives"])
    streak_text = f"  {streak_emoji(streak)} x{multiplier}" if streak >= 2 else ""
    text = (
        f"📚 <b>Savol:</b>\n\n"
        f"🇰🇷 <b>{q['korean']}</b>  <i>({q['romanization']})</i>\n"
        f"nima degan ma'noni anglatadi?\n\n"
        f"{lives_str}  ⭐ {user['score']} ball{streak_text}"
    )
    sent = await bot.send_message(
        chat_id, text,
        reply_markup=quiz_options_kb(q["options"], q["id"]),
        parse_mode=ParseMode.HTML,
    )
    active_quizzes[user_id] = {
        "q": q,
        "msg_id": sent.message_id,
        "start_time": time.time(),
        "chat_id": chat_id,
    }
    await state.set_state(QuizStates.playing)
    await state.update_data(q=q)


@router.callback_query(F.data == "start_quiz")
async def cb_start_quiz(cq: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await ensure_user(cq.from_user.id, cq.from_user.username or "", cq.from_user.full_name or "")
    m = safe_message(cq.message) if cq.message else None
    if not m:
        return
    chat_id = m.chat.id
    await m.delete()
    await send_question(bot, cq.from_user.id, chat_id, state)


@router.callback_query(F.data.startswith("ans:"))
async def cb_answer(cq: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    parts = (cq.data or "").split(":", 2)
    if len(parts) < 3:
        return
    _, word_id_str, chosen = parts
    user_id = cq.from_user.id
    session = active_quizzes.get(user_id)
    if not session:
        await cq.answer("Savol sessiyasi topilmadi.")
        return
    q = session["q"]
    if str(q["id"]) != word_id_str:
        await cq.answer("Bu eski savol.")
        return
    elapsed = time.time() - session["start_time"]
    is_correct = chosen == q["translation"]
    if is_correct:
        streak = await update_score(user_id, 10, correct=True)
        multiplier = min(streak, 5)
        gained = 10 * multiplier
        result_text = (
            f"✅ <b>To'g'ri!</b> +{gained} ball"
            + (f" (x{multiplier} 🔥)" if multiplier > 1 else "")
        )
    else:
        await update_score(user_id, -5, correct=False)
        result_text = f"❌ <b>Noto'g'ri!</b> -5 ball\n✅ To'g'ri javob: <b>{q['translation']}</b>"
    user = await get_user(user_id)
    if not user:
        return
    lives_str = "❤️" * user["lives"] + "🖤" * (3 - user["lives"])
    new_text = (
        f"📚 <b>Savol natijasi:</b>\n\n"
        f"🇰🇷 <b>{q['korean']}</b>  <i>({q['romanization']})</i>\n\n"
        f"{result_text}\n\n"
        f"{lives_str}  ⭐ {user['score']} ball  ⏱️ {elapsed:.1f}s"
    )
    m = safe_message(cq.message) if cq.message else None
    if not m:
        await cq.answer()
        return
    await m.edit_text(new_text, reply_markup=next_or_exit_kb(), parse_mode=ParseMode.HTML)
    active_quizzes.pop(user_id, None)
    new_badges = await check_and_award_badges(user_id)
    if new_badges:
        await bot.send_message(m.chat.id, "🏅 <b>Yangi nishon!</b> " + ", ".join(new_badges), parse_mode=ParseMode.HTML)
    await cq.answer()


@router.callback_query(F.data == "next_question")
async def cb_next_question(cq: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    m = safe_message(cq.message) if cq.message else None
    if not m:
        return
    chat_id = m.chat.id
    await m.delete()
    await send_question(bot, cq.from_user.id, chat_id, state)


@router.callback_query(F.data == "quit_quiz")
async def cb_quit_quiz(cq: CallbackQuery, state: FSMContext) -> None:
    active_quizzes.pop(cq.from_user.id, None)
    await state.clear()
    user = await get_user(cq.from_user.id)
    score = user["score"] if user else 0
    m = safe_message(cq.message) if cq.message else None
    if not m:
        await cq.answer()
        return
    await m.edit_text(
        f"🚪 <b>Quiz tugadi!</b>\n\n⭐ Jami ball: <b>{score}</b>",
        reply_markup=main_menu_kb(),
        parse_mode=ParseMode.HTML,
    )


# ─── ✍️ TYPING GAME ───────────────────────────────────────────────────────────

async def send_typing_question(bot: Bot, user_id: int, chat_id: int, state: FSMContext) -> None:
    user = await get_user(user_id)
    if not user:
        return
    word = await get_random_word_for_typing(user["difficulty"])
    if not word:
        await bot.send_message(chat_id, "❌ So'zlar topilmadi.")
        await state.clear()
        return
    session = active_typing.get(user_id, {})
    current_score = session.get("score", 0)
    current_round = session.get("round", 0) + 1
    streak = user["streak"]
    multiplier = min(streak, 5)
    streak_text = f"  {streak_emoji(streak)} x{multiplier}" if streak >= 2 else ""
    text = (
        f"✍️ <b>So'z Yozing - {current_round}-savol</b>\n\n"
        f"🇰🇷 <b>{word['korean']}</b>\n"
        f"<i>({word['romanization']})</i>\n\n"
        f"📝 Tarjimasini o'zbek tilida yozing:\n\n"
        f"⭐ {user['score']} ball  |  Bu sessiya: +{current_score}{streak_text}\n"
        f"⏱️ {TYPING_TIMEOUT} soniya vaqtingiz bor!"
    )
    exit_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💡 Ko'rsatma", callback_data=f"typing_hint:{word['id']}"),
         InlineKeyboardButton(text="🚪 Chiqish", callback_data="typing_quit")]
    ])
    sent = await bot.send_message(chat_id, text, reply_markup=exit_kb, parse_mode=ParseMode.HTML)
    active_typing[user_id] = {
        "word": word,
        "msg_id": sent.message_id,
        "start_time": time.time(),
        "chat_id": chat_id,
        "score": current_score,
        "round": current_round,
        "hint_used": False,
    }
    await state.set_state(TypingGameStates.playing)
    asyncio.create_task(_typing_timeout(bot, user_id, word["id"]))


async def _typing_timeout(bot: Bot, user_id: int, word_id: int) -> None:
    await asyncio.sleep(TYPING_TIMEOUT)
    session = active_typing.get(user_id)
    if not session or session["word"]["id"] != word_id:
        return
    word = session["word"]
    try:
        await bot.send_message(
            session["chat_id"],
            f"⏰ <b>Vaqt tugadi!</b>\n\n"
            f"🇰🇷 <b>{word['korean']}</b>\n"
            f"✅ To'g'ri javob: <b>{word['translation']}</b>\n\n"
            f"Bu sessiyada: <b>+{session['score']}</b> ball",
            reply_markup=typing_next_or_exit_kb(),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass
    active_typing[user_id]["timed_out"] = True


@router.callback_query(F.data == "start_typing")
async def cb_start_typing(cq: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await ensure_user(cq.from_user.id, cq.from_user.username or "", cq.from_user.full_name or "")
    m = safe_message(cq.message) if cq.message else None
    if not m:
        return
    chat_id = m.chat.id
    active_typing[cq.from_user.id] = {"score": 0, "round": 0}
    await m.delete()
    intro = await bot.send_message(
        chat_id,
        "✍️ <b>So'z Yozing O'yini!</b>\n\n"
        "Koreyscha so'z ko'rsatiladi, siz uning O'zbekcha tarjimasini yozasiz.\n\n"
        "✅ To'g'ri: +15 ball\n❌ Noto'g'ri: -3 ball\n💡 Ko'rsatma: +8 ball\n\nBoshlaylik! 🚀",
        parse_mode=ParseMode.HTML,
    )
    await asyncio.sleep(1)
    try:
        await intro.delete()
    except Exception:
        pass
    await send_typing_question(bot, cq.from_user.id, chat_id, state)


@router.message(TypingGameStates.playing)
async def handle_typing_answer(msg: Message, state: FSMContext, bot: Bot) -> None:
    user_id = msg.from_user.id if msg.from_user else 0
    session = active_typing.get(user_id)
    if not session or not session.get("word"):
        await state.clear()
        return
    if session.get("timed_out"):
        return
    word = session["word"]
    user_answer = normalize_answer(msg.text or "")
    correct_variants = [normalize_answer(v.strip()) for v in word["translation"].split("/")]
    is_correct = user_answer in correct_variants
    elapsed = time.time() - session["start_time"]
    hint_used = session.get("hint_used", False)
    if is_correct:
        bonus = 8 if hint_used else 15
        streak = await update_score(user_id, bonus, correct=True)
        multiplier = min(streak, 5)
        gained = bonus * multiplier
        session["score"] = session.get("score", 0) + gained
        speed_bonus = 0
        if elapsed < 5 and not hint_used:
            speed_bonus = 5
            await update_score(user_id, speed_bonus, correct=True)
            session["score"] += speed_bonus
        result = (
            f"✅ <b>To'g'ri!</b> +{gained} ball"
            + (f" (x{multiplier} 🔥)" if multiplier > 1 else "")
            + (f"\n⚡ Tezlik bonusi: +{speed_bonus}" if speed_bonus else "")
        )
    else:
        await update_score(user_id, -3, correct=False)
        result = (
            f"❌ <b>Noto'g'ri!</b> -3 ball\n"
            f"Siz yozdingiz: <i>{msg.text}</i>\n"
            f"✅ To'g'ri javob: <b>{word['translation']}</b>"
        )
    user = await get_user(user_id)
    score = user["score"] if user else 0
    await msg.answer(
        f"✍️ <b>Natija:</b>\n\n"
        f"🇰🇷 <b>{word['korean']}</b> = {word['translation']}\n\n"
        f"{result}\n\n"
        f"⭐ Jami: {score} ball  |  Bu sessiya: +{session['score']}\n"
        f"⏱️ {elapsed:.1f}s",
        reply_markup=typing_next_or_exit_kb(),
        parse_mode=ParseMode.HTML,
    )
    active_typing[user_id] = {
        "word": None, "score": session["score"],
        "round": session.get("round", 0), "chat_id": session["chat_id"],
    }
    new_badges = await check_and_award_badges(user_id)
    if new_badges:
        await bot.send_message(msg.chat.id, "🏅 <b>Yangi nishon!</b> " + ", ".join(new_badges), parse_mode=ParseMode.HTML)


@router.callback_query(F.data.startswith("typing_hint:"))
async def cb_typing_hint(cq: CallbackQuery) -> None:
    user_id = cq.from_user.id
    session = active_typing.get(user_id)
    if not session or not session.get("word"):
        await cq.answer("Sessiya topilmadi!")
        return
    translation = session["word"]["translation"]
    hint = translation[:2] + "_" * (len(translation) - 2) if len(translation) >= 3 else translation[0] + "_"
    session["hint_used"] = True
    active_typing[user_id] = session
    await cq.answer(f"💡 Ko'rsatma: {hint}", show_alert=True)


@router.callback_query(F.data == "typing_next")
async def cb_typing_next(cq: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    m = safe_message(cq.message) if cq.message else None
    if not m:
        return
    user_id = cq.from_user.id
    session = active_typing.get(user_id, {})
    chat_id = m.chat.id
    active_typing[user_id] = {"score": session.get("score", 0), "round": session.get("round", 0), "chat_id": chat_id}
    try:
        await m.delete()
    except Exception:
        pass
    await send_typing_question(bot, user_id, chat_id, state)
    await cq.answer()


@router.callback_query(F.data == "typing_quit")
async def cb_typing_quit(cq: CallbackQuery, state: FSMContext) -> None:
    user_id = cq.from_user.id
    session = active_typing.pop(user_id, {})
    total_score = session.get("score", 0)
    rounds = session.get("round", 0)
    await state.clear()
    m = safe_message(cq.message) if cq.message else None
    if not m:
        await cq.answer()
        return
    await m.edit_text(
        f"✍️ <b>So'z Yozing - Tugadi!</b>\n\n"
        f"📊 Savollar: {rounds}\n🏆 Bu sessiyada: +{total_score} ball\n\nYaxshi o'yin! 👏",
        reply_markup=main_menu_kb(),
        parse_mode=ParseMode.HTML,
    )


# ─── 1v1 BATTLE ───────────────────────────────────────────────────────────────

async def build_battle_questions() -> list:
    questions = []
    for _ in range(BATTLE_Q_COUNT):
        q = await get_random_question()
        if q:
            questions.append(q)
    return questions


@router.callback_query(F.data == "join_battle")
@router.message(Command("battle"))
async def join_battle(update: Union[CallbackQuery, Message], bot: Bot) -> None:
    from_user = update.from_user
    if not from_user:
        return
    user_id = from_user.id
    await ensure_user(user_id, from_user.username or "", from_user.full_name or "")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM battle_queue WHERE user_id=?", (user_id,)) as cur:
            if await cur.fetchone():
                if isinstance(update, CallbackQuery):
                    await update.answer("Siz allaqachon navbatdasiz! ⏳")
                return

        async with db.execute(
            "SELECT user_id FROM battle_queue WHERE user_id!=? ORDER BY joined_at LIMIT 1", (user_id,)
        ) as cur:
            opponent = await cur.fetchone()

        if opponent:
            opponent_id = opponent[0]
            await db.execute("DELETE FROM battle_queue WHERE user_id=?", (opponent_id,))
            questions = await build_battle_questions()
            q_json = json.dumps(questions)
            async with db.execute(
                "INSERT INTO battles (player1, player2, questions, current_q, started_at) VALUES (?,?,?,0,?)",
                (opponent_id, user_id, q_json, time.time()),
            ) as cur:
                battle_id: int = cur.lastrowid or 0
            await db.commit()
            notice = f"⚔️ <b>Raqib topildi! Battle #{battle_id} boshlanmoqda...</b>"
            if isinstance(update, CallbackQuery):
                m = safe_message(update.message) if update.message else None
                if m:
                    await m.edit_text(notice, parse_mode=ParseMode.HTML)
            elif isinstance(update, Message):
                await update.answer(notice, parse_mode=ParseMode.HTML)
            await send_1v1_question(bot, battle_id, opponent_id, 0)
            await send_1v1_question(bot, battle_id, user_id, 0)
        else:
            await db.execute(
                "INSERT OR REPLACE INTO battle_queue (user_id, joined_at) VALUES (?,?)",
                (user_id, time.time()),
            )
            await db.commit()
            cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_battle")]
            ])
            waiting_text = "⏳ <b>Raqib qidirilmoqda...</b>\n\nBoshqa o'yinchi /battle yuborganida o'yin boshlanadi!"
            if isinstance(update, CallbackQuery):
                m = safe_message(update.message) if update.message else None
                if m:
                    await m.edit_text(waiting_text, reply_markup=cancel_kb, parse_mode=ParseMode.HTML)
            elif isinstance(update, Message):
                await update.answer(waiting_text, reply_markup=cancel_kb, parse_mode=ParseMode.HTML)

    if isinstance(update, CallbackQuery):
        await update.answer()


async def send_1v1_question(bot: Bot, battle_id: int, user_id: int, q_index: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM battles WHERE id=?", (battle_id,)) as cur:
            battle = await cur.fetchone()
        if not battle:
            return
        battle = dict(battle)
    questions = json.loads(battle["questions"])
    if q_index >= len(questions):
        await finish_1v1_battle(bot, battle_id)
        return
    q = questions[q_index]
    text = (
        f"⚔️ <b>1v1 Battle #{battle_id}</b>  📊 {q_index + 1}/{len(questions)}\n\n"
        f"🇰🇷 <b>{q['korean']}</b>  <i>({q.get('romanization', '')})</i>\n"
        f"nima degan ma'noni anglatadi?\n\n⏱️ {BATTLE_TIMEOUT} soniya!"
    )
    await bot.send_message(user_id, text, reply_markup=battle_options_kb(battle_id, q["options"]), parse_mode=ParseMode.HTML)
    asyncio.create_task(_1v1_timeout(bot, battle_id, user_id, q_index, q["translation"]))


async def _1v1_timeout(bot: Bot, battle_id: int, user_id: int, q_index: int, correct_answer: str) -> None:
    await asyncio.sleep(BATTLE_TIMEOUT)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT answered FROM battle_answers WHERE battle_id=? AND user_id=? AND q_index=?",
            (battle_id, user_id, q_index),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            await db.execute(
                "INSERT OR IGNORE INTO battle_answers (battle_id, user_id, q_index, answered, correct) VALUES (?,?,?,1,0)",
                (battle_id, user_id, q_index),
            )
            await db.commit()
            try:
                await bot.send_message(user_id, f"⏰ <b>Vaqt tugadi!</b>\n✅ To'g'ri: <b>{correct_answer}</b>", parse_mode=ParseMode.HTML)
            except Exception:
                pass
            await _1v1_check_advance(bot, battle_id, q_index)


@router.callback_query(F.data.startswith("bans:"))
async def cb_1v1_answer(cq: CallbackQuery, bot: Bot) -> None:
    parts = (cq.data or "").split(":", 2)
    if len(parts) < 3:
        return
    _, battle_id_str, chosen = parts
    battle_id = int(battle_id_str)
    user_id = cq.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM battles WHERE id=?", (battle_id,)) as cur:
            battle = await cur.fetchone()
        if not battle:
            await cq.answer("Battle topilmadi!")
            return
        battle = dict(battle)
        if battle["status"] != "active":
            await cq.answer("Battle tugagan!")
            return
        q_index = battle["current_q"]
        questions = json.loads(battle["questions"])
        if q_index >= len(questions):
            await cq.answer("Savollar tugadi!")
            return
        q = questions[q_index]
        async with db.execute(
            "SELECT answered FROM battle_answers WHERE battle_id=? AND user_id=? AND q_index=?",
            (battle_id, user_id, q_index),
        ) as cur:
            existing = await cur.fetchone()
        if existing and existing[0]:
            await cq.answer("Allaqachon javob berdingiz!")
            return
        is_correct = chosen == q["translation"]
        await db.execute(
            "INSERT OR REPLACE INTO battle_answers (battle_id, user_id, q_index, answered, correct) VALUES (?,?,?,1,?)",
            (battle_id, user_id, q_index, 1 if is_correct else 0),
        )
        if is_correct:
            col = "score1" if battle["player1"] == user_id else "score2"
            await db.execute(f"UPDATE battles SET {col}={col}+10 WHERE id=?", (battle_id,))
        await db.commit()
    result = "✅ <b>To'g'ri!</b> +10 ball" if is_correct else f"❌ <b>Noto'g'ri!</b>\n✅ To'g'ri: <b>{q['translation']}</b>"
    m = safe_message(cq.message) if cq.message else None
    if m:
        await m.edit_text(f"⚔️ <b>Battle #{battle_id}</b>\n\n{result}", parse_mode=ParseMode.HTML)
    await cq.answer()
    await _1v1_check_advance(bot, battle_id, q_index)


async def _1v1_check_advance(bot: Bot, battle_id: int, q_index: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM battles WHERE id=?", (battle_id,)) as cur:
            battle = await cur.fetchone()
        if not battle or battle["status"] != "active":
            return
        battle = dict(battle)
        async with db.execute(
            "SELECT COUNT(*) FROM battle_answers WHERE battle_id=? AND q_index=? AND answered=1",
            (battle_id, q_index),
        ) as cur:
            row = await cur.fetchone()
            answered_count = row[0] if row else 0
    total_q = len(json.loads(battle["questions"]))
    if answered_count >= 2:
        next_q = q_index + 1
        if next_q >= total_q:
            await finish_1v1_battle(bot, battle_id)
        else:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE battles SET current_q=? WHERE id=?", (next_q, battle_id))
                await db.commit()
            await send_1v1_question(bot, battle_id, battle["player1"], next_q)
            await send_1v1_question(bot, battle_id, battle["player2"], next_q)


async def finish_1v1_battle(bot: Bot, battle_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM battles WHERE id=? AND status='active'", (battle_id,)) as cur:
            battle = await cur.fetchone()
        if not battle:
            return
        battle = dict(battle)
        await db.execute("UPDATE battles SET status='finished' WHERE id=?", (battle_id,))
        await db.commit()
    p1, p2 = battle["player1"], battle["player2"]
    s1, s2 = battle["score1"], battle["score2"]
    if s1 > s2:
        winner, loser = p1, p2
    elif s2 > s1:
        winner, loser = p2, p1
    else:
        winner = loser = None
    if winner and loser:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET wins=wins+1, score=score+30 WHERE user_id=?", (winner,))
            await db.execute("UPDATE users SET losses=losses+1 WHERE user_id=?", (loser,))
            await db.commit()
    for uid, my_score in [(p1, s1), (p2, s2)]:
        other = s2 if uid == p1 else s1
        if winner is None:
            result_text = "🤝 <b>Durrang!</b>"
        elif uid == winner:
            result_text = "🏆 <b>G'alaba!</b> +30 ball"
        else:
            result_text = "😢 <b>Mag'lubiyat!</b>"
        try:
            await bot.send_message(
                uid,
                f"⚔️ <b>Battle #{battle_id} tugadi!</b>\n\nSizning ballingiz: <b>{my_score}</b>\nRaqibning bali: <b>{other}</b>\n\n{result_text}",
                reply_markup=main_menu_kb(),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


@router.callback_query(F.data == "cancel_battle")
async def cb_cancel_battle(cq: CallbackQuery) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM battle_queue WHERE user_id=?", (cq.from_user.id,))
        await db.commit()
    m = safe_message(cq.message) if cq.message else None
    if m:
        await m.edit_text("❌ Battle bekor qilindi.", reply_markup=main_menu_kb())
    await cq.answer()


# ─── 2v2 TEAM BATTLE ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "team_battle_menu")
async def cb_team_battle_menu(cq: CallbackQuery) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT team_side, COUNT(*) as cnt FROM team_battle_queue GROUP BY team_side"
        ) as cur:
            rows = await cur.fetchall()
    counts = {r[0]: r[1] for r in rows}
    red_cnt = counts.get("red", 0)
    blue_cnt = counts.get("blue", 0)
    text = (
        f"👥 <b>2v2 Jamoa Jangi</b>\n\n"
        f"🔴 Qizil jamoa: {red_cnt}/2\n"
        f"🔵 Ko'k jamoa: {blue_cnt}/2\n\n"
        f"Ikkala jamoa to'lishi bilan o'yin boshlanadi!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔴 Qizil jamoaga qo'shil", callback_data="tb_join:red"),
            InlineKeyboardButton(text="🔵 Ko'k jamoaga qo'shil", callback_data="tb_join:blue"),
        ],
        [InlineKeyboardButton(text="❌ Navbatdan chiqish", callback_data="tb_leave")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="main_menu")],
    ])
    m = safe_message(cq.message) if cq.message else None
    if not m:
        await cq.answer()
        return
    await m.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await cq.answer()


@router.callback_query(F.data.startswith("tb_join:"))
async def cb_tb_join(cq: CallbackQuery, bot: Bot) -> None:
    side = (cq.data or "").split(":")[1]
    user_id = cq.from_user.id
    await ensure_user(user_id, cq.from_user.username or "", cq.from_user.full_name or "")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT team_side FROM team_battle_queue WHERE user_id=?", (user_id,)) as cur:
            existing = await cur.fetchone()
        if existing:
            team_name = "🔴 Qizil" if existing[0] == 'red' else "🔵 Ko'k"
            await cq.answer(f"Siz allaqachon {team_name} jamoada!", show_alert=True)
            return
        async with db.execute("SELECT COUNT(*) FROM team_battle_queue WHERE team_side=?", (side,)) as cur:
            row = await cur.fetchone()
        if row and row[0] >= 2:
            await cq.answer("Bu jamoa to'liq!", show_alert=True)
            return
        await db.execute(
            "INSERT INTO team_battle_queue (user_id, team_side, joined_at) VALUES (?,?,?)",
            (user_id, side, time.time()),
        )
        await db.commit()
        async with db.execute("SELECT user_id FROM team_battle_queue WHERE team_side='red' ORDER BY joined_at") as cur:
            red_players = [r[0] for r in await cur.fetchall()]
        async with db.execute("SELECT user_id FROM team_battle_queue WHERE team_side='blue' ORDER BY joined_at") as cur:
            blue_players = [r[0] for r in await cur.fetchall()]
        if len(red_players) >= 2 and len(blue_players) >= 2:
            red1, red2 = red_players[:2]
            blue1, blue2 = blue_players[:2]
            for uid in [red1, red2, blue1, blue2]:
                await db.execute("DELETE FROM team_battle_queue WHERE user_id=?", (uid,))
            questions = await build_battle_questions()
            q_json = json.dumps(questions)
            async with db.execute(
                "INSERT INTO team_battles (red1, red2, blue1, blue2, questions, started_at) VALUES (?,?,?,?,?,?)",
                (red1, red2, blue1, blue2, q_json, time.time()),
            ) as cur:
                battle_id: int = cur.lastrowid or 0
            await db.commit()
            for uid in [red1, red2, blue1, blue2]:
                team = "red" if uid in [red1, red2] else "blue"
                team_label = "🔴 Qizil" if team == 'red' else "🔵 Ko'k"
                try:
                    await bot.send_message(
                        uid,
                        f"👥 <b>2v2 Jang #{battle_id} boshlanmoqda!</b>\nSiz {team_label} jamoasidasiz.",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
            for uid in [red1, red2, blue1, blue2]:
                await send_team_battle_question(bot, battle_id, uid, 0)
            return
    team_label = "🔴 Qizil" if side == 'red' else "🔵 Ko'k"
    await cq.answer(f"✅ {team_label} jamoaga qo'shildingiz!", show_alert=True)
    await cb_team_battle_menu(cq)


@router.callback_query(F.data == "tb_leave")
async def cb_tb_leave(cq: CallbackQuery) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM team_battle_queue WHERE user_id=?", (cq.from_user.id,))
        await db.commit()
    await cq.answer("✅ Navbatdan chiqildingiz.", show_alert=True)
    await cb_main_menu(cq)


async def send_team_battle_question(bot: Bot, battle_id: int, user_id: int, q_index: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM team_battles WHERE id=?", (battle_id,)) as cur:
            battle = await cur.fetchone()
        if not battle:
            return
        battle = dict(battle)
    if battle["status"] != "active":
        return
    questions = json.loads(battle["questions"])
    if q_index >= len(questions):
        await finish_team_battle(bot, battle_id)
        return
    q = questions[q_index]
    team_label = "🔴 Qizil" if user_id in (battle["red1"], battle["red2"]) else "🔵 Ko'k"
    text = (
        f"👥 <b>2v2 Jang #{battle_id}</b>  📊 {q_index + 1}/{len(questions)}\n"
        f"Jamoa: {team_label}  |  🔴 {battle['red_score']} — 🔵 {battle['blue_score']}\n\n"
        f"🇰🇷 <b>{q['korean']}</b>  <i>({q.get('romanization', '')})</i>\n"
        f"nima degan ma'noni anglatadi?\n\n⏱️ {BATTLE_TIMEOUT} soniya!"
    )
    try:
        await bot.send_message(user_id, text, reply_markup=team_battle_answer_kb(battle_id, q_index, q["options"]), parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"send_team_battle_question xatosi: {e}")
    asyncio.create_task(_team_timeout(bot, battle_id, user_id, q_index, q["translation"]))


async def _team_timeout(bot: Bot, battle_id: int, user_id: int, q_index: int, correct_answer: str) -> None:
    await asyncio.sleep(BATTLE_TIMEOUT)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT answered FROM team_battle_answers WHERE battle_id=? AND user_id=? AND q_index=?",
            (battle_id, user_id, q_index),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            await db.execute(
                "INSERT OR IGNORE INTO team_battle_answers (battle_id, user_id, q_index, answered, correct) VALUES (?,?,?,1,0)",
                (battle_id, user_id, q_index),
            )
            await db.commit()
            try:
                await bot.send_message(user_id, f"⏰ <b>Vaqt tugadi!</b>\n✅ To'g'ri: <b>{correct_answer}</b>", parse_mode=ParseMode.HTML)
            except Exception:
                pass
            await _team_check_advance(bot, battle_id, q_index)


@router.callback_query(F.data.startswith("tbans:"))
async def cb_team_battle_answer(cq: CallbackQuery, bot: Bot) -> None:
    parts = (cq.data or "").split(":", 3)
    if len(parts) < 4:
        return
    _, battle_id_str, q_index_str, chosen = parts
    battle_id = int(battle_id_str)
    q_index = int(q_index_str)
    user_id = cq.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM team_battles WHERE id=?", (battle_id,)) as cur:
            battle = await cur.fetchone()
        if not battle:
            await cq.answer("Jang topilmadi!")
            return
        battle = dict(battle)
        if battle["status"] != "active":
            await cq.answer("Jang tugagan!")
            return
        all_players = [battle["red1"], battle["red2"], battle["blue1"], battle["blue2"]]
        if user_id not in all_players:
            await cq.answer("Siz bu jangda qatnashmaysiz!")
            return
        async with db.execute(
            "SELECT answered FROM team_battle_answers WHERE battle_id=? AND user_id=? AND q_index=?",
            (battle_id, user_id, q_index),
        ) as cur:
            existing = await cur.fetchone()
        if existing and existing[0]:
            await cq.answer("Allaqachon javob berdingiz!")
            return
        questions = json.loads(battle["questions"])
        if q_index >= len(questions):
            await cq.answer("Bu savol eski!")
            return
        q = questions[q_index]
        is_correct = chosen == q["translation"]
        await db.execute(
            "INSERT OR REPLACE INTO team_battle_answers (battle_id, user_id, q_index, answered, correct) VALUES (?,?,?,1,?)",
            (battle_id, user_id, q_index, 1 if is_correct else 0),
        )
        if is_correct:
            col = "red_score" if user_id in (battle["red1"], battle["red2"]) else "blue_score"
            await db.execute(f"UPDATE team_battles SET {col}={col}+10 WHERE id=?", (battle_id,))
        await db.commit()
    team_label = "🔴 Qizil" if user_id in (battle["red1"], battle["red2"]) else "🔵 Ko'k"
    result = "✅ <b>To'g'ri!</b> Jamoangizga +10!" if is_correct else f"❌ <b>Noto'g'ri!</b>\n✅ To'g'ri: <b>{q['translation']}</b>"
    m = safe_message(cq.message) if cq.message else None
    if m:
        await m.edit_text(f"👥 <b>2v2 Jang #{battle_id}</b>  [{team_label}]\n\n{result}", parse_mode=ParseMode.HTML)
    await cq.answer()
    await _team_check_advance(bot, battle_id, q_index)


async def _team_check_advance(bot: Bot, battle_id: int, q_index: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM team_battles WHERE id=?", (battle_id,)) as cur:
            battle = await cur.fetchone()
        if not battle or battle["status"] != "active":
            return
        battle = dict(battle)
        async with db.execute(
            "SELECT COUNT(*) FROM team_battle_answers WHERE battle_id=? AND q_index=? AND answered=1",
            (battle_id, q_index),
        ) as cur:
            row = await cur.fetchone()
            answered_count = row[0] if row else 0
    total_q = len(json.loads(battle["questions"]))
    all_players = [battle["red1"], battle["red2"], battle["blue1"], battle["blue2"]]
    if answered_count >= len(all_players):
        next_q = q_index + 1
        if next_q >= total_q:
            await finish_team_battle(bot, battle_id)
        else:
            for uid in all_players:
                await send_team_battle_question(bot, battle_id, uid, next_q)


async def finish_team_battle(bot: Bot, battle_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM team_battles WHERE id=? AND status='active'", (battle_id,)) as cur:
            battle = await cur.fetchone()
        if not battle:
            return
        battle = dict(battle)
        await db.execute("UPDATE team_battles SET status='finished' WHERE id=?", (battle_id,))
        await db.commit()
    red_score = battle["red_score"]
    blue_score = battle["blue_score"]
    red_players = [battle["red1"], battle["red2"]]
    blue_players = [battle["blue1"], battle["blue2"]]
    if red_score > blue_score:
        winners, losers = red_players, blue_players
        winner_label = "🔴 Qizil jamoa g'alaba qozondi!"
    elif blue_score > red_score:
        winners, losers = blue_players, red_players
        winner_label = "🔵 Ko'k jamoa g'alaba qozondi!"
    else:
        winners, losers = [], []
        winner_label = "🤝 Durrang!"
    async with aiosqlite.connect(DB_PATH) as db:
        for uid in winners:
            await db.execute("UPDATE users SET wins=wins+1, score=score+40 WHERE user_id=?", (uid,))
        for uid in losers:
            await db.execute("UPDATE users SET losses=losses+1 WHERE user_id=?", (uid,))
        await db.commit()
    for uid in red_players + blue_players:
        my_team = "🔴 Qizil" if uid in red_players else "🔵 Ko'k"
        my_score = red_score if uid in red_players else blue_score
        if winners and uid in winners:
            personal = "🏆 <b>G'alaba!</b> +40 ball!"
        elif losers:
            personal = "😢 <b>Mag'lubiyat!</b>"
        else:
            personal = "🤝 Durrang!"
        try:
            await bot.send_message(
                uid,
                f"👥 <b>2v2 Jang #{battle_id} tugadi!</b>\n\n🔴 Qizil: <b>{red_score}</b>\n🔵 Ko'k: <b>{blue_score}</b>\n\n🏆 <b>{winner_label}</b>\n\nSizning jamoangiz ({my_team}): {my_score}\n{personal}",
                reply_markup=main_menu_kb(),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


# ─── ADMIN PANEL ─────────────────────────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(msg: Message) -> None:
    if not msg.from_user or not is_admin(msg.from_user.id):
        await msg.answer("❌ Ruxsat yo'q.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        word_count = list(await db.execute_fetchall("SELECT COUNT(*) FROM words"))[0][0]
        user_count = list(await db.execute_fetchall("SELECT COUNT(*) FROM users"))[0][0]
        easy_count = list(await db.execute_fetchall("SELECT COUNT(*) FROM words WHERE difficulty='easy'"))[0][0]
        med_count = list(await db.execute_fetchall("SELECT COUNT(*) FROM words WHERE difficulty='medium'"))[0][0]
        hard_count = list(await db.execute_fetchall("SELECT COUNT(*) FROM words WHERE difficulty='hard'"))[0][0]
    text = (
        f"👨‍💻 <b>Admin Panel</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{user_count}</b>\n"
        f"📚 So'zlar: <b>{word_count}</b>\n"
        f"  🟢 Oson: {easy_count}\n  🟡 O'rta: {med_count}\n  🔴 Qiyin: {hard_count}\n\n"
        f"Buyruqlar:\n"
        f"/add_word, /list_words, /delete_word [id]\n"
        f"/import_pdf, /export_words\n"
        f"/rebalance — Difficulty qayta taqsimlash\n"
        f"/cleanup — 🧹 To'liq tozalash\n"
        f"/broadcast [xabar], /reset_user [id]\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📤 So'zlar PDFi", callback_data="admin_export_pdf"),
            InlineKeyboardButton(text="🧹 Tozalash", callback_data="admin_cleanup"),
        ],
        [
            InlineKeyboardButton(text="🟢 Oson", callback_data="admin_words:easy"),
            InlineKeyboardButton(text="🟡 O'rta", callback_data="admin_words:medium"),
            InlineKeyboardButton(text="🔴 Qiyin", callback_data="admin_words:hard"),
        ],
        [InlineKeyboardButton(text="⚖️ Difficulty Taqsimlash", callback_data="admin_rebalance")],
    ])
    await msg.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)


@router.callback_query(F.data == "admin_cleanup")
@router.message(Command("cleanup"))
async def cmd_cleanup(update: Union[CallbackQuery, Message]) -> None:
    if isinstance(update, CallbackQuery):
        if not is_admin(update.from_user.id):
            await update.answer("❌ Ruxsat yo'q")
            return
        m = safe_message(update.message) if update.message else None
        if m:
            await m.answer("⏳ Tozalanmoqda...", parse_mode=ParseMode.HTML)
        await update.answer("⏳ Tozalanmoqda...")
    else:
        if not update.from_user or not is_admin(update.from_user.id):
            await update.answer("❌ Ruxsat yo'q.")
            return
        wait = await update.answer("⏳ To'liq tozalash boshlanmoqda...")

    result = await full_cleanup_words()

    async with aiosqlite.connect(DB_PATH) as db:
        total = list(await db.execute_fetchall("SELECT COUNT(*) FROM words"))[0][0]
        easy_c = list(await db.execute_fetchall("SELECT COUNT(*) FROM words WHERE difficulty='easy'"))[0][0]
        med_c = list(await db.execute_fetchall("SELECT COUNT(*) FROM words WHERE difficulty='medium'"))[0][0]
        hard_c = list(await db.execute_fetchall("SELECT COUNT(*) FROM words WHERE difficulty='hard'"))[0][0]

    result_text = (
        f"🧹 <b>To'liq tozalash tugadi!</b>\n\n"
        f"🗑️ Dublikatlar o'chirildi: <b>{result['duplicates_removed']}</b>\n"
        f"🔧 Bo'sh javoblar tuzatildi: <b>{result['wrongs_fixed']}</b>\n\n"
        f"📊 <b>Hozirgi holat:</b>\n"
        f"Jami so'zlar: {total}\n"
        f"🟢 Oson: {easy_c}\n"
        f"🟡 O'rta: {med_c}\n"
        f"🔴 Qiyin: {hard_c}"
    )

    if isinstance(update, CallbackQuery):
        m = safe_message(update.message) if update.message else None
        if m:
            await m.answer(result_text, parse_mode=ParseMode.HTML)
    else:
        try:
            await wait.edit_text(result_text, parse_mode=ParseMode.HTML)
        except Exception:
            await update.answer(result_text, parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "admin_rebalance")
@router.message(Command("rebalance"))
async def cmd_rebalance(update: Union[CallbackQuery, Message]) -> None:
    if isinstance(update, CallbackQuery):
        if not is_admin(update.from_user.id):
            await update.answer("❌ Ruxsat yo'q")
            return
        await update.answer("⏳ Qayta taqsimlanmoqda...")
    else:
        if not update.from_user or not is_admin(update.from_user.id):
            await update.answer("❌ Ruxsat yo'q.")
            return
    counts = await rebalance_difficulties()
    total = sum(counts.values())
    result_text = (
        f"✅ <b>Difficulty qayta taqsimlandi!</b>\n\n"
        f"Jami: {total} so'z\n"
        f"🟢 Oson: {counts['easy']} ({counts['easy']*100//total if total else 0}%)\n"
        f"🟡 O'rta: {counts['medium']} ({counts['medium']*100//total if total else 0}%)\n"
        f"🔴 Qiyin: {counts['hard']} ({counts['hard']*100//total if total else 0}%)"
    )
    if isinstance(update, CallbackQuery):
        m = safe_message(update.message) if update.message else None
        if m:
            await m.answer(result_text, parse_mode=ParseMode.HTML)
    else:
        await update.answer(result_text, parse_mode=ParseMode.HTML)


@router.callback_query(F.data.startswith("admin_words:"))
async def cb_admin_words_by_diff(cq: CallbackQuery) -> None:
    if not is_admin(cq.from_user.id):
        await cq.answer("❌ Ruxsat yo'q")
        return
    diff = (cq.data or "").split(":")[1]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, korean, translation FROM words WHERE difficulty=? ORDER BY id DESC LIMIT 15", (diff,)
        ) as cur:
            words = [dict(r) for r in await cur.fetchall()]
    if not words:
        await cq.answer(f"{difficulty_label(diff)} darajada so'z yo'q!", show_alert=True)
        return
    lines = [f"📚 <b>{difficulty_label(diff)} so'zlari:</b>\n"]
    for w in words:
        lines.append(f"#{w['id']} {w['korean']} → {w['translation']}")
    m = safe_message(cq.message) if cq.message else None
    if m:
        await m.answer("\n".join(lines), parse_mode=ParseMode.HTML)
    await cq.answer()


@router.callback_query(F.data == "admin_export_pdf")
async def cb_admin_export_pdf(cq: CallbackQuery, bot: Bot) -> None:
    if not is_admin(cq.from_user.id):
        await cq.answer("❌ Ruxsat yo'q")
        return
    await cq.answer("⏳ PDF tayyorlanmoqda...")
    m = safe_message(cq.message) if cq.message else None
    if not m:
        return
    await _export_words_pdf(bot, m.chat.id)


@router.message(Command("export_words"))
async def cmd_export_words(msg: Message, bot: Bot) -> None:
    if not msg.from_user or not is_admin(msg.from_user.id):
        await msg.answer("❌ Ruxsat yo'q.")
        return
    wait_msg = await msg.answer("⏳ PDF tayyorlanmoqda...")
    await _export_words_pdf(bot, msg.chat.id)
    try:
        await wait_msg.delete()
    except Exception:
        pass


async def _export_words_pdf(bot: Bot, chat_id: int) -> None:
    pdf_path = "/tmp/korean_words_export.pdf"
    success = await generate_words_pdf(pdf_path)
    if success and os.path.exists(pdf_path):
        with open(pdf_path, "rb") as f:
            pdf_data = f.read()
        await bot.send_document(
            chat_id,
            document=BufferedInputFile(pdf_data, filename="korean_words.pdf"),
            caption="📚 <b>Korean So'zlar Ro'yxati</b>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await bot.send_message(chat_id, "❌ PDF yaratishda xato.")


# ─── PDF IMPORT ───────────────────────────────────────────────────────────────

@router.message(Command("import_pdf"))
async def cmd_import_pdf(msg: Message, state: FSMContext) -> None:
    if not msg.from_user or not is_admin(msg.from_user.id):
        await msg.answer("❌ Ruxsat yo'q.")
        return
    text = (
        "📥 <b>PDF fayldan so'z import</b>\n\n"
        "Format: <code>한국어 | romanization | Tarjima | Xato1 | Xato2 | Xato3 | daraja</code>\n\n"
        "💡 Daraja ko'rsatilmasa — avtomatik teng taqsimlanadi!\n\n"
        "Bekor qilish: /cancel"
    )
    await msg.answer(text, parse_mode=ParseMode.HTML)
    await state.set_state(ImportPdfState.waiting_file)


@router.message(ImportPdfState.waiting_file, F.document)
async def handle_pdf_import(msg: Message, state: FSMContext, bot: Bot) -> None:
    if not msg.from_user or not is_admin(msg.from_user.id):
        return
    document: Document = msg.document
    if not document.file_name or not document.file_name.lower().endswith(".pdf"):
        await msg.answer("❌ Faqat PDF fayl yuboring!")
        return
    wait_msg = await msg.answer("⏳ PDF yuklab olinmoqda...")
    tmp_path = f"/tmp/import_{document.file_unique_id}.pdf"
    try:
        await bot.download(document, destination=tmp_path)
    except Exception as e:
        await wait_msg.edit_text(f"❌ Fayl yuklab olinmadi: {e}")
        await state.clear()
        return
    if not os.path.exists(tmp_path):
        await wait_msg.edit_text("❌ Fayl saqlanmadi.")
        await state.clear()
        return
    await wait_msg.edit_text("⏳ PDF tahlil qilinmoqda...")
    imported, errors = await import_words_from_pdf(tmp_path)
    try:
        os.remove(tmp_path)
    except Exception:
        pass
    async with aiosqlite.connect(DB_PATH) as db:
        easy_c = list(await db.execute_fetchall("SELECT COUNT(*) FROM words WHERE difficulty='easy'"))[0][0]
        med_c = list(await db.execute_fetchall("SELECT COUNT(*) FROM words WHERE difficulty='medium'"))[0][0]
        hard_c = list(await db.execute_fetchall("SELECT COUNT(*) FROM words WHERE difficulty='hard'"))[0][0]
        total_c = easy_c + med_c + hard_c
    result_text = (
        f"✅ <b>Import tugadi!</b>\n\n📥 Qo'shildi: <b>{imported}</b> ta so'z\n\n"
        f"📊 <b>Hozirgi taqsimlash:</b>\n"
        f"🟢 Oson: {easy_c} ({easy_c*100//total_c if total_c else 0}%)\n"
        f"🟡 O'rta: {med_c} ({med_c*100//total_c if total_c else 0}%)\n"
        f"🔴 Qiyin: {hard_c} ({hard_c*100//total_c if total_c else 0}%)\n"
    )
    if errors:
        result_text += f"\n⚠️ Xabarnomalar ({len(errors)}):\n" + "\n".join(f"• {e}" for e in errors[:8])
    await wait_msg.edit_text(result_text, parse_mode=ParseMode.HTML)
    await state.clear()


@router.message(ImportPdfState.waiting_file)
async def handle_pdf_import_wrong(msg: Message) -> None:
    await msg.answer("📎 PDF fayl yuboring yoki /cancel.")


@router.message(Command("cancel"))
async def cmd_cancel(msg: Message, state: FSMContext) -> None:
    await state.clear()
    await msg.answer("❌ Bekor qilindi.", reply_markup=main_menu_kb())


@router.message(Command("broadcast"))
async def cmd_broadcast(msg: Message, bot: Bot) -> None:
    if not msg.from_user or not is_admin(msg.from_user.id):
        await msg.answer("❌ Ruxsat yo'q.")
        return
    text_parts = (msg.text or "").split(maxsplit=1)
    if len(text_parts) < 2:
        await msg.answer("Foydalanish: /broadcast [xabar]")
        return
    broadcast_text = text_parts[1]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            users = [r[0] for r in await cur.fetchall()]
    sent = 0
    failed = 0
    wait_msg = await msg.answer(f"📤 Yuborilmoqda... ({len(users)} ta)")
    for uid in users:
        try:
            await bot.send_message(uid, f"📢 {broadcast_text}", parse_mode=ParseMode.HTML)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
    await wait_msg.edit_text(f"✅ Broadcast tugadi!\n✉️ Yuborildi: {sent}\n❌ Xato: {failed}", parse_mode=ParseMode.HTML)


@router.message(Command("reset_user"))
async def cmd_reset_user(msg: Message) -> None:
    if not msg.from_user or not is_admin(msg.from_user.id):
        await msg.answer("❌ Ruxsat yo'q.")
        return
    parts = (msg.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await msg.answer("Foydalanish: /reset_user [user_id]")
        return
    uid = int(parts[1])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
        if not row:
            await msg.answer(f"❌ {uid} ID li foydalanuvchi topilmadi.")
            return
        await db.execute(
            "UPDATE users SET score=0, wins=0, losses=0, streak=0, max_streak=0, lives=3, badges='' WHERE user_id=?",
            (uid,),
        )
        await db.commit()
    await msg.answer(f"✅ {row[0]} ({uid}) statistikasi nolga tushirildi.")


@router.message(Command("add_word"))
async def cmd_add_word(msg: Message, state: FSMContext) -> None:
    if not msg.from_user or not is_admin(msg.from_user.id):
        await msg.answer("❌ Ruxsat yo'q.")
        return
    await msg.answer("🇰🇷 Koreyscha so'zni kiriting (masalan: 가게):")
    await state.set_state(AddWordStates.korean)


@router.message(AddWordStates.korean)
async def aw_korean(msg: Message, state: FSMContext) -> None:
    await state.update_data(korean=(msg.text or "").strip())
    await msg.answer("📝 Romanizatsiyani kiriting. O'tkazib yuborish uchun - yuboring:")
    await state.set_state(AddWordStates.romanization)


@router.message(AddWordStates.romanization)
async def aw_romanization(msg: Message, state: FSMContext) -> None:
    text = (msg.text or "").strip()
    await state.update_data(romanization="" if text == "-" else text)
    await msg.answer("✅ To'g'ri tarjimani kiriting:")
    await state.set_state(AddWordStates.translation)


@router.message(AddWordStates.translation)
async def aw_translation(msg: Message, state: FSMContext) -> None:
    await state.update_data(translation=(msg.text or "").strip())
    await msg.answer("❌ 1-noto'g'ri javobni kiriting:")
    await state.set_state(AddWordStates.wrong1)


@router.message(AddWordStates.wrong1)
async def aw_wrong1(msg: Message, state: FSMContext) -> None:
    await state.update_data(wrong1=(msg.text or "").strip())
    await msg.answer("❌ 2-noto'g'ri javobni kiriting:")
    await state.set_state(AddWordStates.wrong2)


@router.message(AddWordStates.wrong2)
async def aw_wrong2(msg: Message, state: FSMContext) -> None:
    await state.update_data(wrong2=(msg.text or "").strip())
    skip_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ O'tkazib yuborish", callback_data="skip_wrong3")]
    ])
    await msg.answer("❌ 3-noto'g'ri javob (ixtiyoriy):", reply_markup=skip_kb)
    await state.set_state(AddWordStates.wrong3)


@router.callback_query(F.data == "skip_wrong3")
async def cb_skip_wrong3(cq: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(wrong3=None)
    diff_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🟢 Oson", callback_data="aw_diff:easy"),
        InlineKeyboardButton(text="🟡 O'rta", callback_data="aw_diff:medium"),
        InlineKeyboardButton(text="🔴 Qiyin", callback_data="aw_diff:hard"),
    ]])
    m = safe_message(cq.message) if cq.message else None
    if m:
        await m.edit_text("🎯 Qiyinchilik darajasini tanlang:", reply_markup=diff_kb)
    await state.set_state(AddWordStates.difficulty)


@router.message(AddWordStates.wrong3)
async def aw_wrong3(msg: Message, state: FSMContext) -> None:
    await state.update_data(wrong3=(msg.text or "").strip() or None)
    diff_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🟢 Oson", callback_data="aw_diff:easy"),
        InlineKeyboardButton(text="🟡 O'rta", callback_data="aw_diff:medium"),
        InlineKeyboardButton(text="🔴 Qiyin", callback_data="aw_diff:hard"),
    ]])
    await msg.answer("🎯 Qiyinchilik darajasini tanlang:", reply_markup=diff_kb)
    await state.set_state(AddWordStates.difficulty)


@router.callback_query(F.data.startswith("aw_diff:"))
async def cb_aw_difficulty(cq: CallbackQuery, state: FSMContext) -> None:
    diff = (cq.data or "").split(":")[1]
    data = await state.get_data()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO words (korean, romanization, translation, wrong1, wrong2, wrong3, difficulty, added_by) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (data["korean"], data.get("romanization", ""), data["translation"],
             data["wrong1"], data["wrong2"], data.get("wrong3"), diff, cq.from_user.id),
        )
        await db.commit()
    await state.clear()
    m = safe_message(cq.message) if cq.message else None
    if m:
        await m.edit_text(
            f"✅ <b>So'z qo'shildi!</b>\n\n🇰🇷 {data['korean']} → {data['translation']}\nDaraja: {difficulty_label(diff)}",
            parse_mode=ParseMode.HTML,
        )


@router.message(Command("list_words"))
async def cmd_list_words(msg: Message) -> None:
    if not msg.from_user or not is_admin(msg.from_user.id):
        await msg.answer("❌ Ruxsat yo'q.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, korean, translation, difficulty FROM words ORDER BY id DESC LIMIT 20"
        ) as cur:
            words = await cur.fetchall()
    if not words:
        await msg.answer("📭 So'zlar yo'q.")
        return
    lines = ["📚 <b>So'zlar ro'yxati (oxirgi 20):</b>\n"]
    for w in words:
        lines.append(f"#{w['id']} 🇰🇷 {w['korean']} → {w['translation']}  [{w['difficulty']}]")
    await msg.answer("\n".join(lines), parse_mode=ParseMode.HTML)


@router.message(Command("delete_word"))
async def cmd_delete_word(msg: Message) -> None:
    if not msg.from_user or not is_admin(msg.from_user.id):
        await msg.answer("❌ Ruxsat yo'q.")
        return
    parts = (msg.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await msg.answer("Foydalanish: /delete_word id")
        return
    word_id = int(parts[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM words WHERE id=?", (word_id,))
        await db.commit()
    await msg.answer(f"✅ #{word_id} so'z o'chirildi.")


@router.message(Command("help"))
async def cmd_help(msg: Message) -> None:
    text = (
        "🇰🇷 <b>Korean Bot V3 - Yordam</b>\n\n"
        "/start — Botni ishga tushirish\n"
        "/translate [so'z] — Tarjima (UZ↔KR)\n"
        "/tarjima [so'z] — Tarjima (UZ↔KR)\n"
        "/leaderboard — Reyting\n"
        "/battle — 1v1 jang\n"
        "/help — Yordam\n\n"
        "🎮 <b>Quiz:</b> To'g'ri +10, Noto'g'ri -5\n"
        "✍️ <b>So'z Yozing:</b> +15 ball\n"
        "🌐 <b>Tarjima:</b> DB + Google Translate UZ↔KR\n"
        "🎭 <b>Mafia:</b> 4-6 kishi, rollar bilan\n"
        "⚔️ <b>1v1 Battle:</b> G'olib +30 ball\n"
        "👥 <b>2v2 Jang:</b> G'olib jamoa +40 ball\n\n"
        "🎭 <b>Mafia rollari:</b>\n"
        "• 🔴 Don — Bosh mafia\n"
        "• 🔴 Mafia — Oddiy mafia\n"
        "• 💚 Shifokor — Bir kishini saqlab qoladi\n"
        "• 🔵 Detektiv — Bir kishini tekshiradi\n"
        "• ⚪ Fuqaro — Ovoz bilan mafia topadi\n"
    )
    await msg.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


# ─── MAIN ─────────────────────────────────────────────────────────────────────

async def main() -> None:
    await init_db()
    prepare_korean_font()
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    dp.include_router(router)        # Asosiy router
    dp.include_router(mafia_router)  # 🎭 Mafia o'yini routeri

    logger.info("🚀 Korean Bot V3 ishga tushdi! Mafia + Tarjima (DB+Google) yoqilgan.")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    asyncio.run(main())