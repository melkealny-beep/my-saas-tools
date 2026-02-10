#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏥 HAKEEM Medical Bot v3.4 - CLINIC EDITION
- Clinic Info & Booking System
- Admin Notifications for new appointments
- Knowledge Base Integration (Payments/Location)
"""

import os
import logging
import httpx
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction

# ============================================================================
# CONFIGURATION
# ============================================================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID") # هتوصل عليه رسايل الحجز

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

def get_knowledge():
    try:
        if os.path.exists("knowledge.txt"):
            with open("knowledge.txt", "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception as e:
        logger.error(f"Error: {e}")
    return "معلومات العيادة غير متوفرة حالياً."

# ============================================================================
# ENGINES
# ============================================================================

class MedicalEngine:
    async def get_response(self, query: str, bot, chat_id: int):
        local_info = get_knowledge()
        
        context_prompt = f"""
        أنت المساعد الذكي لعيادة الدكتور. استخدم المرجع التالي للرد:
        ---
        {local_info}
        ---
        سؤال المريض: {query}
        
        تعليمات هامة:
        1. إذا سأل عن العنوان أو الدفع، أعطه التفاصيل من المرجع.
        2. إذا أراد الحجز، اطلب منه (الاسم، رقم الهاتف، التخصص المطلبو).
        3. كن ودوداً جداً ومحترفاً.
        """

        # 1. Groq
        resp = await self._groq_call(context_prompt, bot, chat_id)
        if resp: return resp, "Groq"
        
        # 2. Gemini fallback
        resp = await self._gemini_call(context_prompt, bot, chat_id)
        if resp: return resp, "Gemini"
        
        return None, None

    async def _groq_call(self, full_prompt, bot, chat_id):
        if not GROQ_API_KEY: return None
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "system", "content": "أنت مساعد عيادة طبية."}, {"role": "user", "content": full_prompt}]
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(GROQ_URL, json=payload, headers=headers)
                if r.status_code == 200: return r.json()['choices'][0]['message']['content']
        except: return None

    async def _gemini_call(self, full_prompt, bot, chat_id):
        if not GEMINI_API_KEY: return None
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            url = f"{GEMINI_BASE_URL}?key={GEMINI_API_KEY}"
            payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(url, json=payload)
                if r.status_code == 200: return r.json()['candidates'][0]['content']['parts'][0]['text']
        except: return None

engine = MedicalEngine()

# ============================================================================
# HANDLERS
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [["🏥 حجز موعد"], ["📍 العنوان وطرق الدفع"], ["❓ استشارة طبية"]]
    await update.message.reply_text(
        "🏥 أهلاً بك في عيادة الدكتور.\nأنا مساعدك الذكي، كيف يمكنني مساعدتك اليوم؟",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user
    
    print(f"[📨] رسالة من {user.first_name}: {text}")

    # تفقد لو الرسالة تحتوي على بيانات حجز (اسم ورقم)
    if any(keyword in text for keyword in ["حجز", "اسم", "رقم", "تليفون"]):
        if ADMIN_ID:
            alert_text = f"🚨 **طلب حجز جديد!**\n\n👤 المريض: {user.first_name}\n🆔 المعرف: {user.id}\n📝 الرسالة: {text}\n⏰ الوقت: {datetime.now().strftime('%H:%M')}"
            try:
                await context.bot.send_message(chat_id=ADMIN_ID, text=alert_text)
                print(f"[🔔] تم إرسال تنبيه حجز للمسؤول")
            except Exception as e:
                logger.error(f"Admin Notify Error: {e}")

    wait_msg = await update.message.reply_text("🤔 جاري الرد عليك...")
    response, used = await engine.get_response(text, context.bot, update.message.chat_id)
    await wait_msg.delete()
    
    if response:
        await update.message.reply_text(response)
    else:
        await update.message.reply_text("⚠️ نعتذر، يرجى المحاولة لاحقاً أو الاتصال بالعيادة مباشرة.")

def main():
    if not TELEGRAM_TOKEN: return
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    print("🚀 حكيم v3.4 (نسخة العيادة) يعمل الآن...")
    app.run_polling()

if __name__ == "__main__":
    main()
