#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import sqlite3
import logging
from datetime import datetime
from typing import Optional
from pathlib import Path

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, filters, ContextTypes
)
import httpx
from dotenv import load_dotenv

# ─── Logging ─────────────────────────────────────────────────────────────────
logs_dir = Path("logs")
logs_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler(logs_dir / 'medical_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ─── Load ENV ─────────────────────────────────────────────────────────────────
script_dir = Path(__file__).parent.absolute()
env_file = script_dir / ".env"
load_dotenv(env_file if env_file.exists() else None)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID       = os.getenv("ADMIN_ID")

if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN غير موجود!")
    sys.exit(1)

# ─── Constants ────────────────────────────────────────────────────────────────
GROQ_API_URL   = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

CLINIC = {
    "doctor":  "د. أحمد سمير عبدالحميد",
    "spec":    "أمراض الجهاز الهضمي والكبد",
    "address": "شربين - شارع باتا أمام مسجد الرحمة برج سراج",
    "phone":   "01121173801",
    "days":    "السبت والثلاثاء والأحد"
}

# States
(
    BOOKING_NAME,
    BOOKING_PHONE,
    BOOKING_DAY,
    BOOKING_CONFIRM,
    CHAT_MODE,
    CHAT_INPUT,
) = range(6)

# ─── Main Keyboard ─────────────────────────────────────────────────────────────
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["📅 حجز موعد"], ["💬 محادثة ذكاء اصطناعي", "🔬 تحليل طبي"], ["👤 ملفي الشخصي", "❓ مساعدة"]],
    resize_keyboard=True
)

# ─── Database ─────────────────────────────────────────────────────────────────
class PatientDatabase:
    def __init__(self, db_path: str = "patients.db"):
        self.db_path = db_path
        self._init()

    def _init(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                appointment_day TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                message TEXT,
                response TEXT,
                api_used TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            conn.commit()
        logger.info("✓ Database initialized")

    def save_patient(self, telegram_id, name, phone, day):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''INSERT OR REPLACE INTO patients
                    (telegram_id, name, phone, appointment_day, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                    (telegram_id, name, phone, day))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"save_patient error: {e}")
            return False

    def get_patient(self, telegram_id):
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    'SELECT * FROM patients WHERE telegram_id = ?', (telegram_id,)
                ).fetchone()
            if row:
                return {'id': row[0], 'telegram_id': row[1], 'name': row[2],
                        'phone': row[3], 'appointment_day': row[4], 'created_at': row[5]}
            return None
        except Exception as e:
            logger.error(f"get_patient error: {e}")
            return None

    def get_all_patients(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                return conn.execute(
                    'SELECT name, phone, appointment_day, created_at FROM patients ORDER BY created_at DESC'
                ).fetchall()
        except Exception as e:
            logger.error(f"get_all_patients error: {e}")
            return []

    def count(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                return conn.execute('SELECT COUNT(*) FROM patients').fetchone()[0]
        except:
            return 0

    def save_chat(self, telegram_id, message, response, api_used):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    'INSERT INTO chat_history (telegram_id, message, response, api_used) VALUES (?, ?, ?, ?)',
                    (telegram_id, message, response, api_used)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"save_chat error: {e}")


# ─── Groq API ─────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = f"""أنت "حكيم" - المساعد الذكي لعيادة {CLINIC['doctor']}، متخصص في {CLINIC['spec']}.

معلومات العيادة:
- الدكتور: {CLINIC['doctor']}
- التخصص: {CLINIC['spec']}
- العنوان: {CLINIC['address']}
- التليفون: {CLINIC['phone']}
- مواعيد الكشف: {CLINIC['days']}

تعليمات الرد:
- تكلم بالعربي العامي المصري المبسط
- لما حد يسلم أو يبعت كلام عام: رحب بيه واسأله إيه اللي تقدر تساعده فيه
- لما حد يسأل سؤال طبي: اشرحله بتفصيل (أسباب، أعراض، نصايح)، وفي الآخر قوله يستشير الدكتور
- لما حد يسأل عن الحجز أو الموعد: قوله يكتب "عاوز احجز" أو يضغط زرار "📅 حجز موعد"
- لما حد يسأل عن العيادة أو الدكتور: ديله المعلومات الكاملة
- متضيفش تحذير طبي في ردود التحيات والكلام العام، بس ضيفه في الردود الطبية فقط
- استخدم إيموجي بشكل خفيف"""


async def groq_chat(message: str, context_str: str = "") -> Optional[str]:
    if not GROQ_API_KEY:
        return "خدمة الذكاء الاصطناعي غير متاحة حالياً."
    try:
        prompt = SYSTEM_PROMPT
        if context_str:
            prompt += f"\n\nمعلومات المريض: {context_str}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                GROQ_API_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": message}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 800
                }
            )
            r.raise_for_status()
            return r.json()['choices'][0]['message']['content']
    except httpx.TimeoutException:
        return "الرد بياخد وقت، حاول تاني."
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return None


async def gemini_analyze(query: str, context_str: str = "") -> Optional[str]:
    if not GEMINI_API_KEY:
        return "خدمة التحليل الطبي غير متاحة حالياً."
    try:
        instruction = f"""أنت مساعد طبي متخصص في أمراض الجهاز الهضمي والكبد لعيادة {CLINIC['doctor']}.
قدم تحليلاً طبياً مفصلاً باللغة العربية المبسطة.
في النهاية أضف: ⚠️ هذا للمعلومات فقط، استشر الطبيب دائماً."""
        if context_str:
            instruction += f"\nالمريض: {context_str}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{GEMINI_API_URL}?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"parts": [{"text": query}]}],
                    "systemInstruction": {"parts": [{"text": instruction}]},
                    "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1000}
                }
            )
            r.raise_for_status()
            data = r.json()
            if data.get('candidates'):
                return data['candidates'][0]['content']['parts'][0]['text']
        return None
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return None


# ─── Bot ──────────────────────────────────────────────────────────────────────
class MedicalBot:
    def __init__(self):
        self.db = PatientDatabase()

    # ── Helpers ──────────────────────────────────────────────────────────────
    def _is_confirm(self, text: str) -> bool:
        confirms = ["✅", "أيوه", "ايوه", "اه", "آه", "أه", "نعم", "يلا", "اكد",
                    "أكد", "تأكيد", "تمام", "صح", "موافق", "وافق", "ok", "okay", "yes"]
        return any(w in text.lower() for w in confirms)

    def _is_cancel(self, text: str) -> bool:
        cancels = ["❌", "لأ", "لا", "الغ", "إلغاء", "cancel", "مش عايز", "مش عاوز"]
        return any(w in text.lower() for w in cancels)

    async def _send_main_menu(self, update: Update, msg: str = "اختار من القائمة:"):
        await update.message.reply_text(msg, reply_markup=MAIN_KEYBOARD)

    # ── /start ────────────────────────────────────────────────────────────────
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        name = update.effective_user.first_name
        await update.message.reply_text(
            f"🏥 أهلاً وسهلاً يا {name}!\n\n"
            f"أنا حكيم، المساعد الذكي لعيادة {CLINIC['doctor']}\n"
            f"متخصص في {CLINIC['spec']} 🩺\n\n"
            f"📍 {CLINIC['address']}\n"
            f"📞 {CLINIC['phone']}\n"
            f"🗓 {CLINIC['days']}\n\n"
            "اسألني أي سؤال أو اختار من القائمة:",
            reply_markup=MAIN_KEYBOARD
        )

    # ── Help ──────────────────────────────────────────────────────────────────
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "📋 إيه اللي أقدر أعمله:\n\n"
            "📅 حجز موعد - احجز في العيادة\n"
            "💬 محادثة AI - اسأل أي سؤال طبي\n"
            "🔬 تحليل طبي - تحليل عميق بـ Gemini\n"
            "👤 ملفي - بياناتك المحفوظة\n\n"
            f"📍 {CLINIC['address']}\n"
            f"📞 {CLINIC['phone']}\n"
            f"🗓 {CLINIC['days']}",
            reply_markup=MAIN_KEYBOARD
        )

    # ── General AI message ────────────────────────────────────────────────────
    async def handle_general_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text

        # زرار الرئيسية
        if any(w in text for w in ["🏠", "الرئيسية", "رجوع", "القائمة"]):
            await self._send_main_menu(update)
            return

        user_id = update.effective_user.id
        await update.message.chat.send_action("typing")

        patient = self.db.get_patient(user_id)
        ctx = f"{patient['name']}" if patient else ""

        response = await groq_chat(text, ctx)
        if response:
            await update.message.reply_text(response, reply_markup=MAIN_KEYBOARD)
        else:
            await update.message.reply_text("حصل خطأ، حاول تاني. 🙏", reply_markup=MAIN_KEYBOARD)

    # ── Booking Flow ──────────────────────────────────────────────────────────
    async def book_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['booking'] = {}
        await update.message.reply_text(
            "😊 أهلاً! هنحجزلك موعد دلوقتي.\n\n"
            "✏️ اكتب اسمك الكامل:",
            reply_markup=ReplyKeyboardRemove()
        )
        return BOOKING_NAME

    async def book_get_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        name = update.message.text.strip()
        if len(name) < 2:
            await update.message.reply_text("⚠️ من فضلك اكتب اسمك الكامل.")
            return BOOKING_NAME
        context.user_data['booking']['name'] = name
        await update.message.reply_text(f"تمام يا {name} 👍\n\n📞 رقم تليفونك؟")
        return BOOKING_PHONE

    async def book_get_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        phone = update.message.text.strip().replace(" ", "").replace("-", "")
        # التحقق من رقم مصري (01x) أو أي رقم 8+ أرقام
        digits = ''.join(c for c in phone if c.isdigit())
        if len(digits) < 8:
            await update.message.reply_text("⚠️ الرقم مش صح، كتبه تاني من فضلك.")
            return BOOKING_PHONE
        context.user_data['booking']['phone'] = phone
        keyboard = [["السبت", "الثلاثاء", "الأحد"]]
        await update.message.reply_text(
            "📅 إيه اليوم اللي بيناسبك؟",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )
        return BOOKING_DAY

    async def book_get_day(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        day = update.message.text.strip()
        context.user_data['booking']['day'] = day
        booking = context.user_data['booking']

        keyboard = [["✅ تأكيد الحجز", "❌ تعديل"]]
        await update.message.reply_text(
            f"📋 تأكيد بيانات الحجز:\n\n"
            f"👤 الاسم: {booking['name']}\n"
            f"📞 التليفون: {booking['phone']}\n"
            f"📅 اليوم: {booking['day']}\n"
            f"📍 العيادة: {CLINIC['address']}\n\n"
            "البيانات صح؟",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )
        return BOOKING_CONFIRM

    async def book_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text = update.message.text

        if self._is_cancel(text):
            context.user_data['booking'] = {}
            await update.message.reply_text(
                "تمام! اكتب اسمك الكامل من الأول:",
                reply_markup=ReplyKeyboardRemove()
            )
            return BOOKING_NAME

        if self._is_confirm(text):
            booking = context.user_data.get('booking', {})
            if not booking.get('name') or not booking.get('phone'):
                await update.message.reply_text("حصل مشكلة، ابدأ من الأول.", reply_markup=MAIN_KEYBOARD)
                return ConversationHandler.END

            success = self.db.save_patient(user_id, booking['name'], booking['phone'], booking.get('day', ''))

            if success:
                await update.message.reply_text(
                    f"🎉 تم الحجز بنجاح يا {booking['name']}!\n\n"
                    f"سيتواصل معك فريق العيادة لتأكيد الوقت.\n\n"
                    f"📞 {CLINIC['phone']}\n"
                    f"📍 {CLINIC['address']}\n"
                    f"🗓 {CLINIC['days']}",
                    reply_markup=MAIN_KEYBOARD
                )
                # إشعار الأدمن
                if ADMIN_ID:
                    try:
                        await context.bot.send_message(
                            chat_id=ADMIN_ID,
                            text=f"🔔 حجز جديد!\n\n"
                                 f"👤 {booking['name']}\n"
                                 f"📞 {booking['phone']}\n"
                                 f"📅 {booking.get('day', 'غير محدد')}\n"
                                 f"🆔 TG: {user_id}\n"
                                 f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                        )
                    except Exception as e:
                        logger.error(f"Admin notify error: {e}")
            else:
                await update.message.reply_text(
                    "❌ حصل خطأ في الحفظ، حاول تاني.",
                    reply_markup=MAIN_KEYBOARD
                )
            return ConversationHandler.END

        # لو كتب حاجة تانية
        keyboard = [["✅ تأكيد الحجز", "❌ تعديل"]]
        await update.message.reply_text(
            "اضغط على أحد الزرارين 👆",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )
        return BOOKING_CONFIRM

    async def book_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("تم الإلغاء.", reply_markup=MAIN_KEYBOARD)
        return ConversationHandler.END

    # ── Chat AI Flow ──────────────────────────────────────────────────────────
    async def chat_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [["🤖 Groq - سريع", "🧠 Gemini - تحليل عميق"], ["🏠 رجوع"]]
        await update.message.reply_text(
            "💬 اختار نوع الذكاء الاصطناعي:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        return CHAT_MODE

    async def chat_select_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        if "رجوع" in text or "🏠" in text:
            await self._send_main_menu(update)
            return ConversationHandler.END
        if "Groq" in text or "سريع" in text:
            context.user_data['chat_mode'] = 'groq'
            await update.message.reply_text(
                "🤖 Groq جاهز! اسألني أي سؤال:\n(اكتب 'رجوع' للخروج)",
                reply_markup=ReplyKeyboardMarkup([["🏠 رجوع"]], resize_keyboard=True)
            )
        elif "Gemini" in text or "تحليل" in text:
            context.user_data['chat_mode'] = 'gemini'
            await update.message.reply_text(
                "🧠 Gemini جاهز! اكتب سؤالك:\n(اكتب 'رجوع' للخروج)",
                reply_markup=ReplyKeyboardMarkup([["🏠 رجوع"]], resize_keyboard=True)
            )
        else:
            await update.message.reply_text("اختار من الزرارين.")
            return CHAT_MODE
        return CHAT_INPUT

    async def chat_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        # خروج
        if any(w in text for w in ["رجوع", "🏠", "خروج", "الرئيسية", "القائمة"]):
            await self._send_main_menu(update, "رجعنا للقائمة الرئيسية 😊")
            return ConversationHandler.END

        user_id = update.effective_user.id
        await update.message.chat.send_action("typing")

        mode = context.user_data.get('chat_mode', 'groq')
        patient = self.db.get_patient(user_id)
        ctx = patient['name'] if patient else ""

        if mode == 'groq':
            response = await groq_chat(text, ctx)
            label = "🤖 Groq"
        else:
            response = await gemini_analyze(text, ctx)
            label = "🧠 Gemini"

        if response:
            if patient:
                self.db.save_chat(user_id, text, response, mode)
            # تقسيم الرد لو طويل
            if len(response) > 4000:
                for i in range(0, len(response), 4000):
                    await update.message.reply_text(response[i:i+4000])
            else:
                await update.message.reply_text(f"{label}:\n\n{response}")
        else:
            await update.message.reply_text("❌ حصل خطأ، حاول تاني.")

        return CHAT_INPUT

    # ── Profile ───────────────────────────────────────────────────────────────
    async def show_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        patient = self.db.get_patient(update.effective_user.id)
        if patient:
            msg = (f"👤 ملفك الشخصي:\n\n"
                   f"الاسم: {patient['name']}\n"
                   f"التليفون: {patient['phone']}\n"
                   f"اليوم المفضل: {patient['appointment_day'] or 'غير محدد'}\n"
                   f"تاريخ التسجيل: {patient['created_at'][:10]}")
        else:
            msg = "مفيش بيانات مسجلة. احجز موعد الأول 😊"
        await update.message.reply_text(msg, reply_markup=MAIN_KEYBOARD)

    # ── Admin Commands ─────────────────────────────────────────────────────────
    async def show_bookings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not ADMIN_ID or str(update.effective_user.id) != str(ADMIN_ID):
            await update.message.reply_text("❌ للمشرف فقط.")
            return

        patients = self.db.get_all_patients()
        if not patients:
            await update.message.reply_text("📭 مفيش حجوزات لسه.")
            return

        msg = f"📋 الحجوزات ({len(patients)} حجز)\n{'─'*25}\n\n"
        for i, (name, phone, day, created) in enumerate(patients, 1):
            entry = f"#{i} 👤 {name}\n📞 {phone}\n📅 {day or 'غير محدد'}\n🕐 {created[:16]}\n{'─'*20}\n"
            if len(msg) + len(entry) > 4000:
                await update.message.reply_text(msg)
                msg = ""
            msg += entry
        if msg:
            await update.message.reply_text(msg)

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not ADMIN_ID or str(update.effective_user.id) != str(ADMIN_ID):
            await update.message.reply_text("❌ للمشرف فقط.")
            return
        total = self.db.count()
        db_size = Path('patients.db').stat().st_size / 1024 if Path('patients.db').exists() else 0
        await update.message.reply_text(
            f"📊 الإحصائيات:\n\nإجمالي المرضى: {total}\n"
            f"حجم DB: {db_size:.2f} KB\n"
            f"آخر تحديث: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )

    # ── Error handler ─────────────────────────────────────────────────────────
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Error: {context.error}", exc_info=context.error)
        if update and update.message:
            try:
                await update.message.reply_text("❌ حصل خطأ، حاول تاني.", reply_markup=MAIN_KEYBOARD)
            except:
                pass

    # ── Build App ─────────────────────────────────────────────────────────────
    def build(self) -> Application:
        app = Application.builder().token(TELEGRAM_TOKEN).build()

        # ── Booking conversation ──
        # الكلمات اللي بتفتح الحجز
        BOOKING_TRIGGER = (
            r"📅 حجز موعد|"
            r"عايز احجز|عاوز احجز|محتاج احجز|محتاجه احجز|"
            r"أريد حجز|اريد حجز|ابي احجز|بدي احجز|"
            r"عايز اعمل حجز|عاوز اعمل حجز|"
            r"حجزلي|حجزني|احجزلي|احجزني|"
            r"^احجز$|^حجز$|موعد كشف|عايز موعد|عاوز موعد|محتاج موعد"
        )

        booking_conv = ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex(BOOKING_TRIGGER), self.book_start),
            ],
            states={
                BOOKING_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, self.book_get_name)],
                BOOKING_PHONE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, self.book_get_phone)],
                BOOKING_DAY:     [MessageHandler(filters.TEXT & ~filters.COMMAND, self.book_get_day)],
                BOOKING_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.book_confirm)],
            },
            fallbacks=[
                CommandHandler("cancel", self.book_cancel),
                MessageHandler(filters.Regex(r"^/start$"), self.start),
            ],
            allow_reentry=True
        )

        # ── Chat conversation ──
        chat_conv = ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex(r"💬 محادثة ذكاء اصطناعي|🔬 تحليل طبي"), self.chat_start),
            ],
            states={
                CHAT_MODE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, self.chat_select_mode)],
                CHAT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.chat_input)],
            },
            fallbacks=[
                CommandHandler("cancel", self.book_cancel),
                MessageHandler(filters.Regex(r"^/start$"), self.start),
            ],
            allow_reentry=True
        )

        # ── Handlers ──
        app.add_handler(CommandHandler("start", self.start))
        app.add_handler(CommandHandler("help", self.help_command))
        app.add_handler(CommandHandler("stats", self.stats))
        app.add_handler(CommandHandler("bookings", self.show_bookings))
        app.add_handler(booking_conv)
        app.add_handler(chat_conv)
        app.add_handler(MessageHandler(filters.Regex(r"^👤 ملفي الشخصي$"), self.show_profile))
        app.add_handler(MessageHandler(filters.Regex(r"^❓ مساعدة$"), self.help_command))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_general_message))
        app.add_error_handler(self.error_handler)

        return app


def main():
    logger.info("🚀 Starting Hakeem Medical Bot...")
    bot = MedicalBot()
    app = bot.build()
    logger.info("✓ Bot is running!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
