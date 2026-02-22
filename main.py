#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import sqlite3
import logging
from datetime import datetime
from typing import Optional, Dict, List
from pathlib import Path
import asyncio

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes

import httpx
from dotenv import load_dotenv

logs_dir = Path("logs")
logs_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler(logs_dir / 'medical_bot.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

logger.info("=" * 80)
logger.info("MEDICAL BOT INITIALIZATION STARTED")
logger.info("=" * 80)

script_dir = Path(__file__).parent.absolute()
logger.info(f"Script directory: {script_dir}")

env_file = script_dir / ".env"
logger.info(f"Looking for .env file at: {env_file}")

if env_file.exists():
    logger.info(f"✓ Found .env file: {env_file}")
    load_dotenv(env_file)
else:
    logger.warning(f"⚠ .env file not found at {env_file}")
    logger.warning("Falling back to checking current working directory...")
    load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID")

logger.info("=" * 80)
logger.info("VALIDATING REQUIRED TOKENS")
logger.info("=" * 80)

if TELEGRAM_TOKEN:
    logger.info("✓ TELEGRAM_TOKEN is set")
else:
    logger.error("✗ TELEGRAM_TOKEN is NOT set - Bot cannot start!")
    sys.exit(1)

if GROQ_API_KEY:
    logger.info("✓ GROQ_API_KEY is set")
else:
    logger.error("✗ GROQ_API_KEY is NOT set")

if GEMINI_API_KEY:
    logger.info("✓ GEMINI_API_KEY is set")
else:
    logger.warning("✗ GEMINI_API_KEY is NOT set")

if ADMIN_ID:
    logger.info(f"✓ ADMIN_ID is set to: {ADMIN_ID}")
else:
    logger.warning("⚠ ADMIN_ID not set - /stats command will be disabled")

logger.info("=" * 80)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

BRANCHES = {
    "sherbin": {"name": "شربين", "address": "شارع باتا أمام مسجد الرحمة برج سراج", "phone": "01121173801", "days": "السبت والثلاثاء والأحد"}
}

STATE_BOOKING_START = 1
STATE_BOOKING_NAME = 2
STATE_BOOKING_PHONE = 3
STATE_BOOKING_BRANCH = 4
STATE_BOOKING_DATE = 5
STATE_BOOKING_CONFIRM = 6
STATE_CHAT_INPUT = 7
STATE_CHAT_MODE = 8


class PatientDatabase:
    def __init__(self, db_path: str = "patients.db"):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS patients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    appointment_date TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER,
                    message TEXT,
                    response TEXT,
                    api_used TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(telegram_id) REFERENCES patients(telegram_id)
                )
            ''')
            conn.commit()
            conn.close()
            logger.info("✓ Database initialized successfully")
        except Exception as e:
            logger.error(f"✗ Database initialization error: {str(e)}")
            raise

    def add_patient(self, telegram_id, name, phone, branch, appointment_date=None):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO patients 
                (telegram_id, name, phone, branch, appointment_date, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (telegram_id, name, phone, branch, appointment_date))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"✗ Error saving patient: {str(e)}")
            return False

    def get_patient(self, telegram_id):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM patients WHERE telegram_id = ?', (telegram_id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return {
                    'id': row[0], 'telegram_id': row[1], 'name': row[2],
                    'phone': row[3], 'branch': row[4], 'appointment_date': row[5], 'created_at': row[6]
                }
            return None
        except Exception as e:
            logger.error(f"✗ Error fetching patient: {str(e)}")
            return None

    def save_chat(self, telegram_id, message, response, api_used):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO chat_history (telegram_id, message, response, api_used)
                VALUES (?, ?, ?, ?)
            ''', (telegram_id, message, response, api_used))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"✗ Error saving chat history: {str(e)}")

    def get_all_patients(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT name, phone, branch, appointment_date, created_at FROM patients ORDER BY created_at DESC')
            rows = cursor.fetchall()
            conn.close()
            return rows
        except Exception as e:
            logger.error(f"✗ Error fetching all patients: {str(e)}")
            return []

    def get_patient_count(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM patients')
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except Exception as e:
            return 0


class GroqAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.url = GROQ_API_URL
        self.model = "llama-3.3-70b-versatile"

    async def chat(self, message: str, context: str = "", system_prompt: str = None) -> Optional[str]:
        try:
            if not system_prompt:
                system_prompt = """أنت "حكيم" - المساعد الطبي الذكي لعيادة د. أحمد سمير عبدالحميد، متخصص في أمراض الجهاز الهضمي والكبد.

معلومات العيادة:
- الدكتور: أحمد سمير عبدالحميد
- التخصص: أمراض الجهاز الهضمي والكبد
- العنوان: شربين - شارع باتا أمام مسجد الرحمة برج سراج
- التليفون: 01121173801
- مواعيد الكشف: السبت والثلاثاء والأحد

أسلوبك في الرد:
- بتتكلم بالعربي الفصيح المبسط المفهوم لكل الناس
- ردودك مفصلة ومنظمة وتشمل معلومات مفيدة حقيقية
- لما حد يسلم أو يقول "إيه" أو "بقولك" أو كلام عام، رد بترحيب جميل واسأله إيه اللي يقدر يساعده فيه بخصوص أمراض الجهاز الهضمي والكبد
- لما حد يسأل سؤال طبي، اشرحله الموضوع بتفصيل كافي: الأسباب، الأعراض، طرق التعامل معها
- في نهاية كل رد طبي، أضف تنبيه: "⚠️ تنبيه: هذا النظام للمعلومات فقط. يُنصح دائماً باستشارة الطبيب المختص للتشخيص الدقيق والعلاج المناسب."
- لو حد طلب استشارة أو قال محتاج مساعدة، اسأله يفصل أكتر: ما هي الأعراض أو الأسئلة التي يريد الاستفسار عنها؟
- لو حد سأل عن موعد أو العيادة، ديله المعلومات الكاملة
- استخدم إيموجي بشكل معتدل لتنظيم الرد
- ردودك لازم تكون كافية ومفيدة وليست مختصرة جداً"""

            if context:
                system_prompt += f"\nمعلومات المريض: {context}"

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message}
                ],
                "temperature": 0.7,
                "max_tokens": 1000
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                return data['choices'][0]['message']['content']
        except httpx.TimeoutException:
            return "عذراً، الرد يأخذ وقتاً طويلاً. حاول مرة أخرى."
        except Exception as e:
            logger.error(f"✗ Groq API error: {str(e)}")
            return None


class GeminiAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.url = GEMINI_API_URL

    async def analyze(self, query: str, context: str = "") -> Optional[str]:
        try:
            system_instruction = """أنت مساعد طبي متقدم متخصص في أمراض الجهاز الهضمي والكبد.
قدم تحليلاً طبياً مفصلاً باللغة العربية."""
            if context:
                system_instruction += f"\nالسياق: {context}"
            payload = {
                "contents": [{"parts": [{"text": query}]}],
                "systemInstruction": {"parts": [{"text": system_instruction}]},
                "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1000}
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(f"{self.url}?key={self.api_key}", json=payload)
                response.raise_for_status()
                data = response.json()
                if 'candidates' in data and len(data['candidates']) > 0:
                    return data['candidates'][0]['content']['parts'][0]['text']
                return None
        except Exception as e:
            logger.error(f"✗ Gemini API error: {str(e)}")
            return None


class MedicalBot:
    def __init__(self):
        self.db = PatientDatabase()
        self.groq = GroqAPI(GROQ_API_KEY)
        self.gemini = GeminiAPI(GEMINI_API_KEY)
        self.user_sessions = {}

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name
        welcome_msg = f"""🏥 أهلاً وسهلاً في عيادة د. أحمد سمير

مرحباً {user_name}! 👋

أنا المساعد الذكي لعيادة **د. أحمد سمير عبدالحميد**
متخصص في أمراض الجهاز الهضمي والكبد 🩺

📍 شربين - شارع باتا أمام مسجد الرحمة برج سراج
📞 01121173801
🗓 السبت والثلاثاء والأحد

اسألني أي سؤال أو اختار من القائمة:
"""
        keyboard = [
            ["📅 حجز موعد"],
            ["💬 محادثة ذكاء اصطناعي", "🔬 تحليل طبي"],
            ["👤 ملفي الشخصي", "❓ مساعدة"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(welcome_msg, reply_markup=reply_markup)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """🆘 المساعدة والمعلومات

📅 **حجز موعد** - احجز في عيادة د. أحمد سمير
💬 **محادثة AI** - اسأل أي سؤال طبي
🔬 **تحليل طبي** - تحليل طبي عميق
👤 **ملفي** - بياناتك المحفوظة

📍 شربين - شارع باتا أمام مسجد الرحمة برج سراج
📞 01121173801
🗓 السبت والثلاثاء والأحد

يمكنك أيضاً الكتابة مباشرة وسأرد عليك! 😊

⚠️ هذا النظام للمعلومات فقط. استشر الدكتور دائماً للحالات الجدية."""
        await update.message.reply_text(help_text)

    async def handle_general_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """رد على أي رسالة عادية بالذكاء الاصطناعي"""
        user_id = update.effective_user.id
        message = update.message.text

        await update.message.chat.send_action("typing")

        patient = self.db.get_patient(user_id)
        context_str = f"المريض: {patient['name']}" if patient else ""

        response = await self.groq.chat(message, context_str)

        if response:
            await update.message.reply_text(response)
        else:
            await update.message.reply_text("عذراً، حدث خطأ. حاول مرة أخرى. 🙏")

    async def book_appointment(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        patient = self.db.get_patient(user_id)
        context.user_data['booking'] = {}
        if patient:
            msg = f"""لدينا بياناتك بالفعل:
الاسم: {patient['name']}
الهاتف: {patient['phone']}

هل تريد التحديث أم المتابعة؟"""
            keyboard = [["تحديث البيانات", "متابعة الحجز"], ["إلغاء"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(msg, reply_markup=reply_markup)
            return STATE_BOOKING_START
        else:
            await update.message.reply_text("📝 لنبدأ حجز موعدك!\n\nما اسمك الكامل؟")
            return STATE_BOOKING_NAME

    async def booking_get_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['booking']['name'] = update.message.text
        await update.message.reply_text("📞 ما رقم هاتفك؟")
        return STATE_BOOKING_PHONE

    async def booking_get_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['booking']['phone'] = update.message.text
        keyboard = [["شربين"], ["إلغاء"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("🏢 الفرع المتاح:\n\n📍 شربين", reply_markup=reply_markup)
        return STATE_BOOKING_BRANCH

    async def booking_get_branch(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.lower()
        branch_map = {"شربين": "sherbin", "sherbin": "sherbin"}
        branch = branch_map.get(text)
        if not branch:
            await update.message.reply_text("اختر شربين")
            return STATE_BOOKING_BRANCH
        context.user_data['booking']['branch'] = branch
        branch_info = BRANCHES[branch]
        msg = f"""✅ الفرع: {branch_info['name']}
العنوان: {branch_info['address']}
الهاتف: {branch_info['phone']}

📅 ما التاريخ المفضل لديك؟ (مثال: 2026-03-15 أو اكتب 'أقرب وقت')"""
        await update.message.reply_text(msg, reply_markup=ReplyKeyboardRemove())
        return STATE_BOOKING_DATE

    async def booking_get_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['booking']['date'] = update.message.text
        booking = context.user_data['booking']
        msg = f"""📋 ملخص الحجز

الاسم: {booking['name']}
الهاتف: {booking['phone']}
الفرع: {booking['branch'].upper()}
التاريخ: {booking['date']}

تأكيد الحجز؟"""
        keyboard = [["✅ تأكيد"], ["❌ إلغاء"]]
        await update.message.reply_text(msg, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return STATE_BOOKING_CONFIRM

    async def booking_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if update.message.text == "✅ تأكيد":
            booking = context.user_data['booking']
            success = self.db.add_patient(user_id, booking['name'], booking['phone'], booking['branch'], booking['date'])
            if success:
                msg = """✅ تم تأكيد الحجز!

سيتواصل معك فريق عيادة د. أحمد سمير لتأكيد الوقت المناسب.

📞 للتواصل: 01121173801
📍 شربين - شارع باتا أمام مسجد الرحمة برج سراج
🗓 مواعيد الكشف: السبت والثلاثاء والأحد"""

                # إشعار فوري للأدمن
                if ADMIN_ID:
                    try:
                        branch_info = BRANCHES.get(booking['branch'], {})
                        admin_msg = f"""🔔 حجز جديد!

👤 الاسم: {booking['name']}
📞 الهاتف: {booking['phone']}
📍 الفرع: {branch_info.get('name', booking['branch'])}
📅 التاريخ: {booking['date']}
🆔 Telegram ID: {user_id}
🕐 وقت الحجز: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
                        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg)
                    except Exception as e:
                        logger.error(f"✗ Error notifying admin: {str(e)}")
            else:
                msg = "❌ خطأ في حفظ الحجز. حاول مرة أخرى."
        else:
            msg = "❌ تم إلغاء الحجز."
        keyboard = [["📅 حجز جديد"], ["💬 محادثة", "👤 ملفي"], ["🏠 الرئيسية"]]
        await update.message.reply_text(msg, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return ConversationHandler.END

    async def chat_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = """💬 وضع المحادثة الذكية

اختر نوع الذكاء الاصطناعي:
1️⃣ Groq - سريع للأسئلة العامة
2️⃣ Gemini - تحليل طبي عميق"""
        keyboard = [["Groq - محادثة سريعة"], ["Gemini - تحليل عميق"], ["إلغاء"]]
        await update.message.reply_text(msg, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return STATE_CHAT_MODE

    async def select_chat_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        choice = update.message.text
        if "Groq" in choice:
            context.user_data['chat_mode'] = 'groq'
            await update.message.reply_text("🤖 Groq جاهز! اسألني أي سؤال:")
        elif "Gemini" in choice:
            context.user_data['chat_mode'] = 'gemini'
            await update.message.reply_text("🧠 Gemini جاهز! اكتب سؤالك للتحليل:")
        else:
            return ConversationHandler.END
        return STATE_CHAT_INPUT

    async def handle_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        message = update.message.text
        chat_mode = context.user_data.get('chat_mode', 'groq')
        patient = self.db.get_patient(user_id)
        context_str = f"المريض: {patient['name']}" if patient else ""
        await update.message.chat.send_action("typing")
        try:
            if chat_mode == 'groq':
                response = await self.groq.chat(message, context_str)
                api_used = "Groq"
            else:
                response = await self.gemini.analyze(message, context_str)
                api_used = "Gemini"
            if response:
                if patient:
                    self.db.save_chat(user_id, message, response, api_used)
                response_text = response[:2000]
                if len(response) > 2000:
                    response_text += "\n\n...(للمزيد، اسأل عن جزء محدد)"
                await update.message.reply_text(f"🤖 {api_used}:\n\n{response_text}")
            else:
                await update.message.reply_text("❌ خطأ في الرد. حاول مرة أخرى.")
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ: {str(e)}")
        keyboard = [["سؤال آخر"], ["تغيير الوضع", "الرئيسية"], ["خروج"]]
        await update.message.reply_text("ماذا تريد أن تعرف أيضاً؟", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return STATE_CHAT_INPUT

    async def show_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        patient = self.db.get_patient(user_id)
        if patient:
            msg = f"""👤 ملفك الشخصي

الاسم: {patient['name']}
الهاتف: {patient['phone']}
الفرع: {patient['branch'].upper()}
تاريخ الموعد: {patient['appointment_date'] or 'غير محدد'}
تاريخ التسجيل: {patient['created_at']}"""
        else:
            msg = "لا توجد بيانات. احجز موعداً أولاً."
        keyboard = [["📅 تحديث الموعد"], ["🏠 الرئيسية"]]
        await update.message.reply_text(msg, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

    async def show_bookings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not ADMIN_ID or str(user_id) != str(ADMIN_ID):
            await update.message.reply_text("❌ غير مصرح - للمشرف فقط")
            return

        patients = self.db.get_all_patients()
        if not patients:
            await update.message.reply_text("📭 لا توجد حجوزات بعد.")
            return

        total = len(patients)
        msg = f"📋 قائمة الحجوزات ({total} حجز)\n" + "─" * 30 + "\n\n"

        for i, row in enumerate(patients, 1):
            name, phone, branch, date, created_at = row
            branch_name = BRANCHES.get(branch, {}).get('name', branch)
            msg += f"#{i} 👤 {name}\n"
            msg += f"📞 {phone}\n"
            msg += f"📍 {branch_name}\n"
            msg += f"📅 {date or 'غير محدد'}\n"
            msg += f"🕐 {created_at[:16]}\n"
            msg += "─" * 20 + "\n"

            # إرسال على دفعات لو الرسالة طويلة
            if len(msg) > 3500:
                await update.message.reply_text(msg)
                msg = ""

        if msg:
            await update.message.reply_text(msg)

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if ADMIN_ID and str(user_id) == str(ADMIN_ID):
            total = self.db.get_patient_count()
            db_size = Path('patients.db').stat().st_size / 1024 if Path('patients.db').exists() else 0
            msg = f"""📊 إحصائيات النظام

إجمالي المرضى: {total}
حجم قاعدة البيانات: {db_size:.2f} KB
آخر تحديث: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        else:
            msg = "❌ غير مصرح - للمشرف فقط"
        await update.message.reply_text(msg)

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Error: {context.error}")
        if update and update.message:
            try:
                await update.message.reply_text("❌ حدث خطأ. حاول مرة أخرى.")
            except:
                pass

    def create_handlers(self) -> Application:
        app = Application.builder().token(TELEGRAM_TOKEN).build()

        booking_handler = ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex("^📅 حجز موعد$"), self.book_appointment),
                MessageHandler(filters.Regex("^تحديث البيانات$"), self.book_appointment),
                MessageHandler(filters.Regex("^متابعة الحجز$"), self.book_appointment),
            ],
            states={
                STATE_BOOKING_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.book_appointment)],
                STATE_BOOKING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.booking_get_name)],
                STATE_BOOKING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.booking_get_phone)],
                STATE_BOOKING_BRANCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.booking_get_branch)],
                STATE_BOOKING_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.booking_get_date)],
                STATE_BOOKING_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.booking_confirm)],
            },
            fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)]
        )

        chat_handler = ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex("^💬 محادثة ذكاء اصطناعي$"), self.chat_start),
                MessageHandler(filters.Regex("^🔬 تحليل طبي$"), self.chat_start),
            ],
            states={
                STATE_CHAT_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.select_chat_mode)],
                STATE_CHAT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_chat)],
            },
            fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)]
        )

        app.add_handler(CommandHandler("start", self.start))
        app.add_handler(CommandHandler("help", self.help_command))
        app.add_handler(CommandHandler("stats", self.stats))
        app.add_handler(CommandHandler("bookings", self.show_bookings))
        app.add_handler(booking_handler)
        app.add_handler(chat_handler)
        app.add_handler(MessageHandler(filters.Regex("^👤 ملفي الشخصي$"), self.show_profile))
        app.add_handler(MessageHandler(filters.Regex("^❓ مساعدة$"), self.help_command))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_general_message))
        app.add_error_handler(self.error_handler)

        return app


def main():
    logger.info("Starting Medical Bot...")
    bot = MedicalBot()
    app = bot.create_handlers()
    logger.info("Bot is running! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
