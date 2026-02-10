#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏥 Medical Specialist Telegram Bot "HAKEEM" - حكيم الطبي
VERSION 3.1 - MESSAGE HANDLER FIXED
- Full message response system fixed
- Auto-fallback between Groq and Gemini
- No user-visible engine selection
- Proper handler ordering
- Single production-ready file
"""

import os
import sys
import json
import sqlite3
import logging
import asyncio
from datetime import datetime
from typing import Optional, Dict, List
from pathlib import Path

# Telegram
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction
from telegram.error import TelegramError

# HTTP Client
import httpx

# Environment
from dotenv import load_dotenv

# ============================================================================
# ARABIC MESSAGES
# ============================================================================

ARABIC_MESSAGES = {
    "welcome": """🏥 أهلاً بك في بوت 'حكيم' الطبي 👋

أنا هنا لمساعدتك في استشاراتك الطبية الأولية.
اطرح أسئلتك عن الأعراض والأمراض والعلاجات.

⚠️ ملاحظة مهمة: هذا البوت لتقديم معلومات طبية أولية فقط وليس بديلاً عن استشارة الطبيب.

ابدأ بكتابة سؤالك الآن:""",
    
    "help": """🆘 **المساعدة والمعلومات**

📋 **كيفية الاستخدام:**
1. اكتب سؤالك الطبي مباشرة
2. سأحلل السؤال وأعطيك إجابة مفصلة
3. يمكنك متابعة السؤال بأسئلة إضافية

**الأوامر المتاحة:**
/start - ابدأ من جديد
/status - معلومات البوت
/profile - ملفك الشخصي
/help - هذه الرسالة

⚠️ **مهم جداً:**
- هذا النظام لأغراض تعليمية فقط
- استشر طبيباً متخصصاً دائماً
- لا تعتمد على هذا البوت وحده للتشخيص""",
    
    "thinking": "🤔 جاري معالجة سؤالك...",
    "error_response": "❌ عذراً، حدث خطأ في معالجة رسالتك. يرجى المحاولة مرة أخرى.",
    "api_error": "⚠️ خدمة المحرك معطلة حالياً. يرجى الانتظار قليلاً والمحاولة مجدداً.",
    "timeout": "⏱️ طلب المعالجة استغرق وقتاً طويلاً. يرجى المحاولة مرة أخرى.",
    "empty_input": "❌ الرجاء كتابة سؤال حقيقي.",
}

# ============================================================================
# LOGGING SETUP
# ============================================================================

logs_dir = Path("logs")
logs_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(logs_dir / 'hakeem_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

logger.info("=" * 80)
logger.info("🏥 HAKEEM MEDICAL BOT v3.1 - INITIALIZING")
logger.info("=" * 80)

# ============================================================================
# ENVIRONMENT SETUP
# ============================================================================

script_dir = Path(__file__).parent.absolute()
env_file = script_dir / ".env"

logger.info(f"Script directory: {script_dir}")

if env_file.exists():
    logger.info(f"✓ Found .env file")
    load_dotenv(env_file)
else:
    logger.warning(f"⚠ .env file not found")
    load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID")

# Validate
if not TELEGRAM_TOKEN:
    logger.error("❌ TELEGRAM_TOKEN not set")
    sys.exit(1)

logger.info("✓ TELEGRAM_TOKEN is set")
logger.info(f"✓ GROQ_API_KEY: {'Set' if GROQ_API_KEY else 'Not set'}")
logger.info(f"✓ GEMINI_API_KEY: {'Set' if GEMINI_API_KEY else 'Not set'}")
logger.info(f"✓ ADMIN_ID: {ADMIN_ID if ADMIN_ID else 'Not set'}")

# API URLs
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

# Bot start time
BOT_START_TIME = datetime.now()

# ============================================================================
# DATABASE
# ============================================================================

class HakeemDatabase:
    """Database for Hakeem bot"""
    
    def __init__(self):
        self.db_path = "hakeem_patients.db"
        logger.info(f"Initializing database: {self.db_path}")
        self.init_database()
    
    def init_database(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    telegram_id INTEGER UNIQUE,
                    first_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chats (
                    id INTEGER PRIMARY KEY,
                    telegram_id INTEGER,
                    user_message TEXT,
                    bot_response TEXT,
                    engine TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
            conn.close()
            logger.info("✓ Database initialized")
        except Exception as e:
            logger.error(f"❌ Database error: {e}")
    
    def add_user(self, user_id: int, name: str):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                'INSERT OR REPLACE INTO users (telegram_id, first_name) VALUES (?, ?)',
                (user_id, name)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error saving user: {e}")
    
    def save_chat(self, user_id: int, msg: str, response: str, engine: str):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO chats (telegram_id, user_message, bot_response, engine) VALUES (?, ?, ?, ?)',
                (user_id, msg, response, engine)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error saving chat: {e}")
    
    def get_user_count(self) -> int:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM users')
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except:
            return 0
    
    def get_chat_count(self) -> int:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM chats')
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except:
            return 0

db = HakeemDatabase()

# ============================================================================
# API ENGINES
# ============================================================================

class MedicalEngine:
    """Medical response engine"""
    
    async def respond(self, query: str, bot = None, chat_id: int = None) -> Optional[str]:
        """Get response from Groq first, fallback to Gemini"""
        
        # Try Groq first
        response = await self._groq_response(query, bot, chat_id)
        if response:
            return response, "Groq"
        
        logger.warning("Groq failed, trying Gemini...")
        
        # Fallback to Gemini
        response = await self._gemini_response(query, bot, chat_id)
        if response:
            return response, "Gemini"
        
        logger.error("Both engines failed")
        return None, "None"
    
    async def _groq_response(self, query: str, bot = None, chat_id: int = None) -> Optional[str]:
        """Get response from Groq"""
        
        if not GROQ_API_KEY:
            logger.warning("Groq API key not set")
            return None
        
        try:
            # Send typing indicator
            if bot and chat_id:
                try:
                    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                except:
                    pass
            
            system_prompt = """أنت طبيب افتراضي متخصص في الرعاية الصحية الأولية.
            قدم إجابات طبية دقيقة وموثوقة.
            دائماً أنصح باستشارة طبيب متخصص.
            استجب باللغة العربية."""
            
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "llama-3.1-70b-versatile",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ],
                "temperature": 0.7,
                "max_tokens": 800
            }
            
            logger.debug("Calling Groq API...")
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(GROQ_API_URL, json=payload, headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    result = data['choices'][0]['message']['content']
                    logger.info(f"✓ Groq response: {len(result)} chars")
                    return result
                else:
                    logger.error(f"Groq HTTP {response.status_code}")
                    return None
        
        except httpx.TimeoutException:
            logger.error("Groq timeout")
            return None
        except Exception as e:
            logger.error(f"Groq error: {e}")
            return None
    
    async def _gemini_response(self, query: str, bot = None, chat_id: int = None) -> Optional[str]:
        """Get response from Gemini"""
        
        if not GEMINI_API_KEY:
            logger.warning("Gemini API key not set")
            return None
        
        try:
            # Send typing indicator
            if bot and chat_id:
                try:
                    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                except:
                    pass
            
            system_instruction = """أنت متخصص طبي ذكي متقدم.
            قدم تحليلاً عميقاً ودقيقاً.
            استجب باللغة العربية بشكل احترافي."""
            
            payload = {
                "contents": [{
                    "parts": [{"text": query}]
                }],
                "systemInstruction": {
                    "parts": [{"text": system_instruction}]
                },
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": 1200
                }
            }
            
            logger.debug("Calling Gemini API...")
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{GEMINI_API_URL}?key={GEMINI_API_KEY}",
                    json=payload
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if 'candidates' in data and len(data['candidates']) > 0:
                        result = data['candidates'][0]['content']['parts'][0]['text']
                        logger.info(f"✓ Gemini response: {len(result)} chars")
                        return result
                    else:
                        logger.warning("Gemini empty response")
                        return None
                else:
                    logger.error(f"Gemini HTTP {response.status_code}")
                    return None
        
        except httpx.TimeoutException:
            logger.error("Gemini timeout")
            return None
        except Exception as e:
            logger.error(f"Gemini error: {e}")
            return None

engine = MedicalEngine()

# ============================================================================
# BOT HANDLERS
# ============================================================================

class HakeemBot:
    """Main bot class"""
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user_id = update.effective_user.id
        name = update.effective_user.first_name
        
        print(f"\n📨 RECEIVED: /start from {user_id}")
        logger.info(f"User {user_id} ({name}) started bot")
        
        db.add_user(user_id, name)
        
        keyboard = [["💬 اسأل حكيم"], ["📊 الحالة", "❓ المساعدة"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(ARABIC_MESSAGES["welcome"], reply_markup=reply_markup)
        logger.info(f"✓ Start message sent to {user_id}")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        user_id = update.effective_user.id
        
        print(f"\n📨 RECEIVED: /help from {user_id}")
        logger.info(f"User {user_id} requested help")
        
        await update.message.reply_text(ARABIC_MESSAGES["help"])
        logger.info(f"✓ Help message sent to {user_id}")
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        user_id = update.effective_user.id
        
        print(f"\n📨 RECEIVED: /status from {user_id}")
        logger.info(f"User {user_id} requested status")
        
        uptime = datetime.now() - BOT_START_TIME
        hours = uptime.seconds // 3600
        minutes = (uptime.seconds % 3600) // 60
        
        user_count = db.get_user_count()
        chat_count = db.get_chat_count()
        
        msg = f"""📊 **حالة البوت**

🏥 بوت: حكيم الطبي
📱 الإصدار: 3.1
🔧 محرك: Groq (Llama 3) مع Gemini للطوارئ

📈 **الإحصائيات:**
👥 عدد المستخدمين: {user_count}
💬 عدد الرسائل: {chat_count}

⏱️ **وقت التشغيل:**
{hours}س {minutes}د

⌚ **الوقت:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        
        await update.message.reply_text(msg)
        logger.info(f"✓ Status sent to {user_id}")
    
    async def profile_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /profile command"""
        user_id = update.effective_user.id
        name = update.effective_user.first_name
        
        print(f"\n📨 RECEIVED: /profile from {user_id}")
        logger.info(f"User {user_id} viewed profile")
        
        msg = f"""👤 **ملفك الشخصي**

الاسم: {name}
المعرّف: {user_id}
البوت: حكيم الطبي v3.1"""
        
        await update.message.reply_text(msg)
        logger.info(f"✓ Profile sent to {user_id}")
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle ALL text messages - THIS IS THE KEY HANDLER"""
        user_id = update.effective_user.id
        chat_id = update.message.chat_id
        text = update.message.text
        
        # ✅ THIS PRINT CONFIRMS MESSAGE RECEIVED IN TERMUX
        print(f"\n" + "=" * 80)
        print(f"📨 RECEIVED MESSAGE FROM USER: {user_id}")
        print(f"📝 MESSAGE TEXT: {text[:100]}")
        print(f"⏰ TIME: {datetime.now().strftime('%H:%M:%S')}")
        print("=" * 80)
        
        logger.info(f"Message from {user_id}: {text[:50]}")
        
        # Add user
        db.add_user(user_id, update.effective_user.first_name)
        
        # Check for empty
        if not text or len(text.strip()) == 0:
            await update.message.reply_text(ARABIC_MESSAGES["empty_input"])
            return
        
        # Show "thinking" message
        try:
            thinking_msg = await update.message.reply_text(ARABIC_MESSAGES["thinking"])
        except:
            thinking_msg = None
        
        try:
            # Get response from engine
            print(f"\n⚙️ PROCESSING MESSAGE...")
            response, engine_used = await engine.respond(text, context.bot, chat_id)
            
            if response:
                print(f"✅ RESPONSE READY ({len(response)} chars, Engine: {engine_used})")
                
                # Save to database
                db.save_chat(user_id, text, response, engine_used)
                
                # Format response
                response_text = response[:2000]
                if len(response) > 2000:
                    response_text += "\n\n... (تم قص النص)"
                
                # Delete thinking message if exists
                if thinking_msg:
                    try:
                        await thinking_msg.delete()
                    except:
                        pass
                
                # Send response
                await update.message.reply_text(
                    f"🤖 **حكيم يقول:**\n\n{response_text}"
                )
                
                print(f"✓ RESPONSE SENT TO USER {user_id}\n")
                logger.info(f"✓ Response sent to {user_id}")
            else:
                print(f"❌ NO RESPONSE FROM ENGINES\n")
                
                # Delete thinking message
                if thinking_msg:
                    try:
                        await thinking_msg.delete()
                    except:
                        pass
                
                await update.message.reply_text(ARABIC_MESSAGES["api_error"])
                logger.error(f"No response from engines for user {user_id}")
        
        except asyncio.TimeoutError:
            print(f"⏱️ TIMEOUT\n")
            if thinking_msg:
                try:
                    await thinking_msg.delete()
                except:
                    pass
            await update.message.reply_text(ARABIC_MESSAGES["timeout"])
            logger.error(f"Timeout for user {user_id}")
        
        except Exception as e:
            print(f"❌ ERROR: {e}\n")
            logger.error(f"Handler error: {e}")
            if thinking_msg:
                try:
                    await thinking_msg.delete()
                except:
                    pass
            await update.message.reply_text(ARABIC_MESSAGES["error_response"])
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors"""
        logger.error(f"Error: {context.error}")
        
        if update and update.message:
            try:
                await update.message.reply_text(ARABIC_MESSAGES["error_response"])
            except:
                pass

# ============================================================================
# BOT SETUP
# ============================================================================

async def verify_token(token: str):
    """Verify bot token"""
    print("\n" + "=" * 80)
    print("🔍 VERIFYING BOT TOKEN")
    print("=" * 80 + "\n")
    
    try:
        from telegram import Bot
        bot = Bot(token=token)
        bot_info = await bot.get_me()
        
        print(f"✅ BOT VERIFICATION SUCCESS")
        print(f"   Bot Username: @{bot_info.username}")
        print(f"   Bot ID: {bot_info.id}")
        print(f"   Bot Name: {bot_info.first_name}")
        print(f"\n🔗 Chat with bot: https://t.me/{bot_info.username}")
        print("=" * 80 + "\n")
        
        return True
    except Exception as e:
        print(f"❌ VERIFICATION FAILED: {e}")
        print("=" * 80 + "\n")
        return False

# ============================================================================
# MAIN ASYNC FUNCTION
# ============================================================================

async def main():
    """Main async function"""
    
    logger.info("=" * 80)
    logger.info("STARTING HAKEEM BOT v3.1")
    logger.info("=" * 80)
    
    if not TELEGRAM_TOKEN:
        logger.error("No token!")
        return
    
    # Verify token
    if not await verify_token(TELEGRAM_TOKEN):
        return
    
    logger.info("Creating bot instance...")
    bot_instance = HakeemBot()
    
    logger.info("Creating application...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # ✅ ADD HANDLERS IN CORRECT ORDER
    # Command handlers first
    logger.info("Adding command handlers...")
    app.add_handler(CommandHandler("start", bot_instance.start_command))
    app.add_handler(CommandHandler("help", bot_instance.help_command))
    app.add_handler(CommandHandler("status", bot_instance.status_command))
    app.add_handler(CommandHandler("profile", bot_instance.profile_command))
    
    # Button handlers
    logger.info("Adding button handlers...")
    app.add_handler(MessageHandler(filters.Regex("^💬 اسأل حكيم$"), bot_instance.handle_message))
    app.add_handler(MessageHandler(filters.Regex("^📊 الحالة$"), bot_instance.status_command))
    app.add_handler(MessageHandler(filters.Regex("^❓ المساعدة$"), bot_instance.help_command))
    
    # ✅ MAIN MESSAGE HANDLER - CATCH ALL TEXT MESSAGES
    # This MUST be added last so it catches everything not matched by specific handlers
    logger.info("Adding main message handler...")
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_instance.handle_message))
    
    # Error handler
    logger.info("Adding error handler...")
    app.add_error_handler(bot_instance.error_handler)
    
    logger.info("✓ All handlers added successfully")
    
    # Startup message
    print("\n" + "=" * 80)
    print("🚀 بوت حكيم الطبي - HAKEEM BOT v3.1 READY")
    print("=" * 80)
    print(f"✓ Script: {script_dir / 'medical_bot_complete.py'}")
    print(f"✓ Database: hakeem_patients.db")
    print(f"✓ Logs: logs/hakeem_bot.log")
    print(f"✓ Engine: Groq (Llama 3) with Gemini fallback")
    print(f"✓ Language: Arabic (العربية)")
    print(f"✓ Event Loop: asyncio.run()")
    print("=" * 80)
    print("\n📱 BOT IS LISTENING FOR MESSAGES")
    print("✅ Press Ctrl+C to stop\n")
    print("=" * 80 + "\n")
    
    logger.info("Starting polling...")
    
    try:
        # Initialize
        await app.initialize()
        logger.info("✓ Application initialized")
        
        # Start
        await app.start()
        logger.info("✓ Application started")
        
        # Poll
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("✓ Polling started")
        
        # Keep running
        while True:
            await asyncio.sleep(1)
    
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        print("\n" + "=" * 80)
        print("⏹️  BOT STOPPED")
        print("=" * 80 + "\n")
    
    except Exception as e:
        logger.error(f"Critical error: {e}")
        print(f"\n❌ ERROR: {e}\n")
    
    finally:
        # Cleanup
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        logger.info("✓ Bot shutdown complete")

# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped.\n")
