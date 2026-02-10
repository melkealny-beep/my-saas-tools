#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Medical Specialist Telegram Bot for GI/Liver Disease
UPDATED VERSION WITH DEBUG LOGGING & POLLING
Termux-compatible, modular, production-ready
Features: Groq (fast chat), Gemini (medical reasoning), SQLite database, Two branches
"""

import os
import sys
import json
import sqlite3
import logging
from datetime import datetime
from typing import Optional, Dict, List
from pathlib import Path
import asyncio

# Telegram
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes

# HTTP Client
import httpx

# Environment - FIXED PATH HANDLING
from dotenv import load_dotenv

# ============================================================================
# ENHANCED LOGGING CONFIGURATION
# ============================================================================

# Create logs directory if it doesn't exist
logs_dir = Path("logs")
logs_dir.mkdir(exist_ok=True)

# Configure detailed logging
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

# ============================================================================
# ENVIRONMENT SETUP - FIXED FOR TERMUX
# ============================================================================

# Get the directory of this script
script_dir = Path(__file__).parent.absolute()
logger.info(f"Script directory: {script_dir}")

# Look for .env in the same directory as the script
env_file = script_dir / ".env"
logger.info(f"Looking for .env file at: {env_file}")

if env_file.exists():
    logger.info(f"✓ Found .env file: {env_file}")
    load_dotenv(env_file)
else:
    logger.warning(f"⚠ .env file not found at {env_file}")
    logger.warning("Falling back to checking current working directory...")
    # Try loading from current working directory as fallback
    load_dotenv()

# Tokens & APIs
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID")

# Validate tokens
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
    logger.error("✗ GEMINI_API_KEY is NOT set")

if ADMIN_ID:
    logger.info(f"✓ ADMIN_ID is set to: {ADMIN_ID}")
else:
    logger.warning("⚠ ADMIN_ID not set - /stats command will be disabled")

logger.info("=" * 80)

# API URLs
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

# Branches
BRANCHES = {
    "cairo": {"name": "Cairo", "address": "Address in Cairo", "phone": "+20XXXXXXXXX"},
    "sherbin": {"name": "Sherbin", "address": "Address in Sherbin", "phone": "+20XXXXXXXXX"}
}

logger.info(f"Branches configured: {list(BRANCHES.keys())}")

# Conversation States
STATE_BOOKING_START = 1
STATE_BOOKING_NAME = 2
STATE_BOOKING_PHONE = 3
STATE_BOOKING_BRANCH = 4
STATE_BOOKING_DATE = 5
STATE_BOOKING_CONFIRM = 6
STATE_CHAT_INPUT = 7
STATE_CHAT_MODE = 8

logger.info("Conversation states initialized")

# ============================================================================
# DATABASE MANAGEMENT
# ============================================================================

class PatientDatabase:
    """SQLite database for patient management"""
    
    def __init__(self, db_path: str = "patients.db"):
        self.db_path = db_path
        logger.info(f"Initializing database at: {db_path}")
        self.init_database()
    
    def init_database(self):
        """Initialize database schema"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Patients table
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
            
            # Chat history table (for context)
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
    
    def add_patient(self, telegram_id: int, name: str, phone: str, branch: str, appointment_date: str = None) -> bool:
        """Add or update patient"""
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
            logger.info(f"✓ Patient {telegram_id} saved successfully")
            return True
        except Exception as e:
            logger.error(f"✗ Error saving patient {telegram_id}: {str(e)}")
            return False
    
    def get_patient(self, telegram_id: int) -> Optional[Dict]:
        """Get patient information"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM patients WHERE telegram_id = ?', (telegram_id,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                logger.debug(f"Patient {telegram_id} retrieved from database")
                return {
                    'id': row[0],
                    'telegram_id': row[1],
                    'name': row[2],
                    'phone': row[3],
                    'branch': row[4],
                    'appointment_date': row[5],
                    'created_at': row[6]
                }
            logger.debug(f"No patient found for ID {telegram_id}")
            return None
        except Exception as e:
            logger.error(f"✗ Error fetching patient {telegram_id}: {str(e)}")
            return None
    
    def save_chat(self, telegram_id: int, message: str, response: str, api_used: str):
        """Save chat history"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO chat_history (telegram_id, message, response, api_used)
                VALUES (?, ?, ?, ?)
            ''', (telegram_id, message, response, api_used))
            
            conn.commit()
            conn.close()
            logger.debug(f"Chat history saved for user {telegram_id}")
        except Exception as e:
            logger.error(f"✗ Error saving chat history: {str(e)}")
    
    def get_patient_count(self) -> int:
        """Get total patient count"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM patients')
            count = cursor.fetchone()[0]
            conn.close()
            logger.debug(f"Total patient count: {count}")
            return count
        except Exception as e:
            logger.error(f"✗ Error getting patient count: {str(e)}")
            return 0

# ============================================================================
# API INTEGRATIONS
# ============================================================================

class GroqAPI:
    """Groq API integration for fast chat"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.url = GROQ_API_URL
        self.model = "llama-3.1-70b-versatile"
        logger.info(f"✓ Groq API initialized with model: {self.model}")
    
    async def chat(self, message: str, context: str = "") -> Optional[str]:
        """Send message to Groq API"""
        logger.debug(f"Groq chat request: {message[:100]}")
        try:
            system_prompt = """You are a helpful medical assistant for a GI/Liver specialist. 
            Provide accurate, helpful medical information. Always recommend consulting with a doctor for serious concerns.
            Be professional and compassionate."""
            
            if context:
                system_prompt += f"\nPatient context: {context}"
            
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
                "max_tokens": 500
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.debug("Sending request to Groq API...")
                response = await client.post(self.url, json=payload, headers=headers)
                response.raise_for_status()
                
                data = response.json()
                result = data['choices'][0]['message']['content']
                logger.info(f"✓ Groq API response received ({len(result)} chars)")
                return result
        
        except httpx.TimeoutException:
            logger.error("✗ Groq API timeout")
            return "Sorry, the response is taking too long. Please try again."
        except Exception as e:
            logger.error(f"✗ Groq API error: {str(e)}")
            return None

class GeminiAPI:
    """Google Gemini API for deep medical reasoning"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.url = GEMINI_API_URL
        logger.info("✓ Gemini API initialized")
    
    async def analyze(self, query: str, context: str = "") -> Optional[str]:
        """Deep medical analysis with Gemini"""
        logger.debug(f"Gemini analysis request: {query[:100]}")
        try:
            system_instruction = """You are an advanced medical AI assistant for GI/Liver disease specialists.
            Provide detailed medical insights based on the query.
            Include relevant medical considerations and recommendations for further evaluation."""
            
            if context:
                system_instruction += f"\nContext: {context}"
            
            payload = {
                "contents": [{
                    "parts": [{"text": query}]
                }],
                "systemInstruction": {
                    "parts": [{"text": system_instruction}]
                },
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": 1000,
                }
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.debug("Sending request to Gemini API...")
                response = await client.post(
                    f"{self.url}?key={self.api_key}",
                    json=payload
                )
                response.raise_for_status()
                
                data = response.json()
                if 'candidates' in data and len(data['candidates']) > 0:
                    result = data['candidates'][0]['content']['parts'][0]['text']
                    logger.info(f"✓ Gemini API response received ({len(result)} chars)")
                    return result
                return None
        
        except httpx.TimeoutException:
            logger.error("✗ Gemini API timeout")
            return "Analysis is taking too long. Please try again."
        except Exception as e:
            logger.error(f"✗ Gemini API error: {str(e)}")
            return None

# ============================================================================
# TELEGRAM BOT HANDLERS
# ============================================================================

class MedicalBot:
    """Main bot class"""
    
    def __init__(self):
        logger.info("Initializing MedicalBot class...")
        self.db = PatientDatabase()
        self.groq = GroqAPI(GROQ_API_KEY)
        self.gemini = GeminiAPI(GEMINI_API_KEY)
        self.user_sessions = {}
        logger.info("✓ MedicalBot initialized successfully")
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command"""
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name
        
        logger.info(f"User {user_id} ({user_name}) started the bot")
        
        # Get or create patient
        patient = self.db.get_patient(user_id)
        
        welcome_msg = f"""🏥 Welcome to Medical Appointments & Chat System
        
Hello {user_name}! 👋

This is a specialized system for GI/Liver disease appointments and medical consultation.

Choose what you'd like to do:
"""
        
        keyboard = [
            ["📅 Book Appointment"],
            ["💬 Chat with AI", "🔬 Medical Analysis"],
            ["👤 My Profile", "❓ Help"]
        ]
        
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(welcome_msg, reply_markup=reply_markup)
        logger.info(f"✓ Start message sent to user {user_id}")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Help command"""
        user_id = update.effective_user.id
        logger.info(f"User {user_id} requested help")
        
        help_text = """🆘 Help & Information

📅 **Book Appointment**
Reserve a slot at Cairo or Sherbin branch

💬 **Chat with AI (Groq)**
Fast chat for general medical questions using Llama 3 AI

🔬 **Medical Analysis (Gemini)**
Deep medical analysis and reasoning

👤 **My Profile**
View your saved information

✉️ **Contact Us**
Cairo: +20XXXXXXXXX
Sherbin: +20XXXXXXXXX

⚠️ **Important**: This system is for information only. Always consult with a doctor for serious concerns.
"""
        await update.message.reply_text(help_text)
        logger.info(f"✓ Help message sent to user {user_id}")
    
    # ========== Appointment Booking ==========
    
    async def book_appointment(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start booking flow"""
        user_id = update.effective_user.id
        logger.info(f"User {user_id} initiated appointment booking")
        
        patient = self.db.get_patient(user_id)
        
        context.user_data['booking'] = {}
        
        if patient:
            msg = f"""Already have info for you:
Name: {patient['name']}
Phone: {patient['phone']}

Want to update? Or proceed with booking?"""
            keyboard = [
                ["Update Info", "Proceed with Booking"],
                ["Cancel"]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(msg, reply_markup=reply_markup)
            logger.info(f"User {user_id} has existing profile, showing options")
            return STATE_BOOKING_START
        else:
            await update.message.reply_text("📝 Let's create your appointment!\n\nWhat's your full name?")
            logger.info(f"User {user_id} starting new booking")
            return STATE_BOOKING_NAME
    
    async def booking_get_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get patient name"""
        user_id = update.effective_user.id
        name = update.message.text
        context.user_data['booking']['name'] = name
        logger.info(f"User {user_id} provided name: {name}")
        
        await update.message.reply_text("📞 What's your phone number?")
        return STATE_BOOKING_PHONE
    
    async def booking_get_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get patient phone"""
        user_id = update.effective_user.id
        phone = update.message.text
        context.user_data['booking']['phone'] = phone
        logger.info(f"User {user_id} provided phone: {phone}")
        
        msg = "🏢 Which branch would you prefer?\n\n1️⃣ Cairo\n2️⃣ Sherbin"
        keyboard = [
            ["Cairo"],
            ["Sherbin"],
            ["Cancel"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(msg, reply_markup=reply_markup)
        return STATE_BOOKING_BRANCH
    
    async def booking_get_branch(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get preferred branch"""
        user_id = update.effective_user.id
        branch = update.message.text.lower()
        
        logger.debug(f"User {user_id} selected branch: {branch}")
        
        if branch not in BRANCHES:
            logger.warning(f"User {user_id} provided invalid branch: {branch}")
            await update.message.reply_text("Please choose Cairo or Sherbin")
            return STATE_BOOKING_BRANCH
        
        context.user_data['booking']['branch'] = branch
        
        branch_info = BRANCHES[branch]
        msg = f"""✅ Branch Selected: {branch_info['name']}
Address: {branch_info['address']}
Phone: {branch_info['phone']}

📅 What date would you prefer? (format: YYYY-MM-DD or write 'ASAP')"""
        
        reply_markup = ReplyKeyboardRemove()
        await update.message.reply_text(msg, reply_markup=reply_markup)
        return STATE_BOOKING_DATE
    
    async def booking_get_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get appointment date"""
        user_id = update.effective_user.id
        date_str = update.message.text
        context.user_data['booking']['date'] = date_str
        logger.info(f"User {user_id} selected date: {date_str}")
        
        # Confirm booking
        booking = context.user_data['booking']
        msg = f"""📋 **Booking Summary**

Name: {booking['name']}
Phone: {booking['phone']}
Branch: {booking['branch'].upper()}
Preferred Date: {booking['date']}

Confirm this booking?"""
        
        keyboard = [
            ["✅ Confirm"],
            ["❌ Cancel"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(msg, reply_markup=reply_markup)
        return STATE_BOOKING_CONFIRM
    
    async def booking_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Confirm and save booking"""
        user_id = update.effective_user.id
        
        if update.message.text == "✅ Confirm":
            booking = context.user_data['booking']
            logger.info(f"User {user_id} confirming booking")
            
            success = self.db.add_patient(
                user_id,
                booking['name'],
                booking['phone'],
                booking['branch'],
                booking['date']
            )
            
            if success:
                msg = """✅ **Booking Confirmed!**

Your appointment request has been saved. The doctor's office will contact you shortly to confirm the exact time.

📞 If you don't receive a call within 24 hours, please contact us:
Cairo: +20XXXXXXXXX
Sherbin: +20XXXXXXXXX"""
                logger.info(f"✓ Appointment confirmed for user {user_id}")
            else:
                msg = "❌ Error saving booking. Please try again."
                logger.error(f"✗ Failed to save appointment for user {user_id}")
        else:
            msg = "❌ Booking cancelled."
            logger.info(f"User {user_id} cancelled booking")
        
        keyboard = [
            ["📅 New Booking"],
            ["💬 Chat", "👤 Profile"],
            ["🏠 Home"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(msg, reply_markup=reply_markup)
        return ConversationHandler.END
    
    # ========== Chat Functions ==========
    
    async def chat_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start chat mode"""
        user_id = update.effective_user.id
        logger.info(f"User {user_id} starting chat mode")
        
        msg = """💬 **AI Chat Mode**

Choose your AI:
1️⃣ **Groq (Fast Chat)** - Quick responses using Llama 3
2️⃣ **Gemini (Deep Analysis)** - Detailed medical reasoning"""
        
        keyboard = [
            ["Groq - Fast Chat"],
            ["Gemini - Deep Analysis"],
            ["Cancel"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(msg, reply_markup=reply_markup)
        return STATE_CHAT_MODE
    
    async def select_chat_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Select chat API"""
        user_id = update.effective_user.id
        choice = update.message.text
        
        logger.info(f"User {user_id} selected chat mode: {choice}")
        
        if "Groq" in choice:
            context.user_data['chat_mode'] = 'groq'
            await update.message.reply_text("🤖 Groq Selected! Ask your medical question:")
            logger.debug(f"User {user_id} using Groq mode")
        elif "Gemini" in choice:
            context.user_data['chat_mode'] = 'gemini'
            await update.message.reply_text("🧠 Gemini Selected! Ask for medical analysis:")
            logger.debug(f"User {user_id} using Gemini mode")
        else:
            logger.info(f"User {user_id} cancelled chat mode selection")
            return ConversationHandler.END
        
        return STATE_CHAT_INPUT
    
    async def handle_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle chat messages"""
        user_id = update.effective_user.id
        message = update.message.text
        chat_mode = context.user_data.get('chat_mode', 'groq')
        
        logger.info(f"User {user_id} sent message ({len(message)} chars) via {chat_mode}")
        
        # Get patient context
        patient = self.db.get_patient(user_id)
        context_str = f"Patient: {patient['name']}, Branch: {patient['branch']}" if patient else ""
        
        # Show typing indicator
        logger.debug(f"Showing typing indicator for user {user_id}")
        await update.message.chat.send_action("typing")
        
        try:
            if chat_mode == 'groq':
                logger.debug("Calling Groq API...")
                response = await self.groq.chat(message, context_str)
                api_used = "Groq"
            else:
                logger.debug("Calling Gemini API...")
                response = await self.gemini.analyze(message, context_str)
                api_used = "Gemini"
            
            if response:
                # Save to database
                if patient:
                    self.db.save_chat(user_id, message, response, api_used)
                
                # Format response
                response_text = response[:1000]  # Limit to 1000 chars
                if len(response) > 1000:
                    response_text += "\n\n...(truncated)"
                
                logger.info(f"✓ Response sent to user {user_id}")
                await update.message.reply_text(
                    f"🤖 **{api_used} Response**:\n\n{response_text}"
                )
            else:
                logger.error(f"No response received from API for user {user_id}")
                await update.message.reply_text("❌ Error getting response. Please try again.")
        
        except Exception as e:
            logger.error(f"✗ Chat error for user {user_id}: {str(e)}")
            await update.message.reply_text(f"❌ Error: {str(e)}")
        
        # Ask for another question
        keyboard = [
            ["Ask Another Question"],
            ["Switch Mode", "Go Home"],
            ["Exit Chat"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text("What else would you like to know?", reply_markup=reply_markup)
        return STATE_CHAT_INPUT
    
    # ========== Profile ==========
    
    async def show_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show patient profile"""
        user_id = update.effective_user.id
        logger.info(f"User {user_id} viewing profile")
        
        patient = self.db.get_patient(user_id)
        
        if patient:
            msg = f"""👤 **Your Profile**

Name: {patient['name']}
Phone: {patient['phone']}
Preferred Branch: {patient['branch'].upper()}
Appointment Date: {patient['appointment_date'] or 'Not scheduled'}
Registered: {patient['created_at']}"""
            logger.debug(f"Profile retrieved for user {user_id}")
        else:
            msg = "No profile information. Please book an appointment first."
            logger.debug(f"No profile found for user {user_id}")
        
        keyboard = [
            ["📅 Update Appointment"],
            ["🏠 Home"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(msg, reply_markup=reply_markup)
    
    # ========== Admin/Stats ==========
    
    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin stats"""
        user_id = update.effective_user.id
        logger.info(f"User {user_id} requested stats")
        
        # Only allow specific admin ID
        if ADMIN_ID and str(user_id) == str(ADMIN_ID):
            total_patients = self.db.get_patient_count()
            db_size = Path('patients.db').stat().st_size / 1024 if Path('patients.db').exists() else 0
            
            msg = f"""📊 **System Stats**

Total Patients: {total_patients}
Database: {db_size:.2f} KB
Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
            
            logger.info(f"Stats displayed to admin {user_id}")
        else:
            msg = "❌ Unauthorized - Only admin can access this"
            logger.warning(f"Unauthorized stats access attempt by user {user_id}")
        
        await update.message.reply_text(msg)
    
    # ========== Error Handler ==========
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors"""
        logger.error(f"Update {update} caused error {context.error}")
        logger.error(f"Error traceback: {context.error}")
        
        if update and update.message:
            try:
                await update.message.reply_text("❌ An error occurred. Please try again.")
            except Exception as e:
                logger.error(f"Could not send error message: {str(e)}")
    
    # ========== Main Handler Router ==========
    
    def create_handlers(self) -> Application:
        """Create and return application with handlers"""
        logger.info("Creating application handlers...")
        
        app = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Conversation handler for booking
        booking_handler = ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex("^📅 Book Appointment$"), self.book_appointment),
                MessageHandler(filters.Regex("^Update Info$"), self.book_appointment),
                MessageHandler(filters.Regex("^Proceed with Booking$"), self.book_appointment),
            ],
            states={
                STATE_BOOKING_START: [
                    MessageHandler(filters.Regex("^Update Info$"), self.book_appointment),
                    MessageHandler(filters.Regex("^Proceed with Booking$"), self.book_appointment),
                    MessageHandler(filters.TEXT, self.booking_get_name),
                ],
                STATE_BOOKING_NAME: [MessageHandler(filters.TEXT, self.booking_get_name)],
                STATE_BOOKING_PHONE: [MessageHandler(filters.TEXT, self.booking_get_phone)],
                STATE_BOOKING_BRANCH: [MessageHandler(filters.TEXT, self.booking_get_branch)],
                STATE_BOOKING_DATE: [MessageHandler(filters.TEXT, self.booking_get_date)],
                STATE_BOOKING_CONFIRM: [MessageHandler(filters.TEXT, self.booking_confirm)],
            },
            fallbacks=[MessageHandler(filters.Regex("^Cancel$"), lambda u, c: ConversationHandler.END)]
        )
        
        # Conversation handler for chat
        chat_handler = ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex("^💬 Chat with AI$"), self.chat_start),
                MessageHandler(filters.Regex("^💬 Chat$"), self.chat_start),
            ],
            states={
                STATE_CHAT_MODE: [MessageHandler(filters.TEXT, self.select_chat_mode)],
                STATE_CHAT_INPUT: [
                    MessageHandler(filters.Regex("^Ask Another Question$"), self.handle_chat),
                    MessageHandler(filters.Regex("^Switch Mode$"), self.chat_start),
                    MessageHandler(filters.TEXT & ~filters.Regex("^Go Home$|^Exit Chat$"), self.handle_chat),
                ],
            },
            fallbacks=[MessageHandler(filters.Regex("^Go Home$|^Exit Chat$|^Cancel$"), lambda u, c: ConversationHandler.END)]
        )
        
        # Add handlers
        logger.info("Adding command handlers...")
        app.add_handler(CommandHandler("start", self.start))
        app.add_handler(CommandHandler("help", self.help_command))
        app.add_handler(CommandHandler("profile", self.show_profile))
        app.add_handler(CommandHandler("stats", self.stats))
        
        logger.info("Adding conversation handlers...")
        app.add_handler(booking_handler)
        app.add_handler(chat_handler)
        
        # Medical analysis
        app.add_handler(MessageHandler(filters.Regex("^🔬 Medical Analysis$"), self.chat_start))
        
        # Profile button
        app.add_handler(MessageHandler(filters.Regex("^👤 My Profile$"), self.show_profile))
        
        # Help button
        app.add_handler(MessageHandler(filters.Regex("^❓ Help$"), self.help_command))
        
        # Home
        app.add_handler(MessageHandler(filters.Regex("^🏠 Home$"), self.start))
        
        # Error handler
        logger.info("Adding error handler...")
        app.add_error_handler(self.error_handler)
        
        logger.info("✓ All handlers created successfully")
        return app

# ============================================================================
# MAIN FUNCTION - POLLING VERSION FOR TERMUX
# ============================================================================

def main():
    """Main entry point with polling for Termux"""
    
    logger.info("=" * 80)
    logger.info("STARTING MEDICAL BOT - POLLING MODE")
    logger.info("=" * 80)
    
    # Validate tokens
    if not TELEGRAM_TOKEN:
        logger.error("CRITICAL: TELEGRAM_TOKEN not set in .env")
        logger.error(f"Expected .env file at: {script_dir / '.env'}")
        print("\n" + "=" * 80)
        print("❌ CRITICAL ERROR: TELEGRAM_TOKEN NOT SET")
        print("=" * 80)
        print(f"Please create a .env file at: {script_dir / '.env'}")
        print("\nExample .env content:")
        print("TELEGRAM_TOKEN=your_token_here")
        print("GROQ_API_KEY=your_groq_key")
        print("GEMINI_API_KEY=your_gemini_key")
        print("ADMIN_ID=your_id")
        print("=" * 80 + "\n")
        sys.exit(1)
    
    if not GROQ_API_KEY:
        logger.warning("WARNING: GROQ_API_KEY not set - Groq chat will not work")
    
    if not GEMINI_API_KEY:
        logger.warning("WARNING: GEMINI_API_KEY not set - Gemini analysis will not work")
    
    logger.info("Creating bot instance...")
    bot = MedicalBot()
    
    logger.info("Creating application...")
    app = bot.create_handlers()
    
    logger.info("=" * 80)
    logger.info("STARTING POLLING")
    logger.info("=" * 80)
    logger.info("Bot token: " + (TELEGRAM_TOKEN[:10] + "..." if TELEGRAM_TOKEN else "NOT SET"))
    logger.info("Polling is active and listening for messages...")
    logger.info("=" * 80)
    
    # Print startup message to console
    print("\n" + "=" * 80)
    print("🚀 MEDICAL BOT STARTED SUCCESSFULLY")
    print("=" * 80)
    print(f"✓ Script directory: {script_dir}")
    print(f"✓ .env file: {env_file} ({'Found' if env_file.exists() else 'NOT FOUND'})")
    print(f"✓ Database: patients.db")
    print(f"✓ Log file: logs/medical_bot.log")
    print(f"✓ Polling enabled: YES")
    print(f"✓ Debug logging: ENABLED")
    print(f"✓ Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print("\n📱 Bot is now listening for messages from Telegram...")
    print("✅ Press Ctrl+C to stop the bot\n")
    print("=" * 80 + "\n")
    
    logger.info("Bot is now listening for messages...")
    
    try:
        # Run with polling
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (Ctrl+C)")
        print("\n\n" + "=" * 80)
        print("⏹️  BOT STOPPED")
        print("=" * 80)
        print(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        print("=" * 80 + "\n")
    except Exception as e:
        logger.error(f"CRITICAL ERROR: {str(e)}")
        print(f"\n\n❌ CRITICAL ERROR: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
