#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🏥 HAKEEM Medical Bot v3.2 - FINAL FIX
- Fixed Groq Model (llama-3.3)
- Fixed Gemini API URL structure
- Auto-fallback enabled
- Single file production-ready
"""

import os
import sys
import sqlite3
import logging
import asyncio
from datetime import datetime
from pathlib import Path
import httpx
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction

# ============================================================================
# CONFIGURATION & LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# API Endpoints
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# تم تصحيح الرابط هنا ليتوافق مع مكتبة httpx
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

# ============================================================================
# ENGINES
# ============================================================================

class MedicalEngine:
    async def get_response(self, query: str, bot, chat_id: int):
        # 1. Try Groq
        resp = await self._groq_call(query, bot, chat_id)
        if resp: return resp, "Groq"
        
        # 2. Fallback to Gemini
        logger.warning("Falling back to Gemini...")
        resp = await self._gemini_call(query, bot, chat_id)
        if resp: return resp, "Gemini"
        
        return None, None

    async def _groq_call(self, query, bot, chat_id):
        if not GROQ_API_KEY: return None
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": "أنت طبيب متخصص. قدم نصائح طبية باللغة العربية مع التنبيه لضرورة استشارة الطبيب."},
                    {"role": "user", "content": query}
                ]
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(GROQ_URL, json=payload, headers=headers)
                if r.status_code == 200:
                    return r.json()['choices'][0]['message']['content']
                logger.error(f"Groq Error {r.status_code}: {r.text}")
        except Exception as e: logger.error(f"Groq Exception: {e}")
        return None

    async def _gemini_call(self, query, bot, chat_id):
        if not GEMINI_API_KEY: return None
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            url = f"{GEMINI_BASE_URL}?key={GEMINI_API_KEY}"
            payload = {
                "contents": [{"parts": [{"text": query}]}],
                "systemInstruction": {"parts": [{"text": "أنت طبيب خبير. أجب بالعربية."}]}
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(url, json=payload)
                if r.status_code == 200:
                    return r.json()['candidates'][0]['content']['parts'][0]['text']
                logger.error(f"Gemini Error {r.status_code}: {r.text}")
        except Exception as e: logger.error(f"Gemini Exception: {e}")
        return None

engine = MedicalEngine()

# ============================================================================
# BOT LOGIC
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [["💬 استشارة جديدة"], ["❓ مساعدة"]]
    await update.message.reply_text(
        "🏥 أهلاً بك في حكيم الطبي v3.2\nاكتب سؤالك الطبي الآن وسأجيبك فوراً.",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    
    print(f"\n[📨] رسالة من {user_id}: {text}")
    
    wait_msg = await update.message.reply_text("🤔 جاري تحليل سؤالك طبيًا...")
    
    response, used = await engine.get_response(text, context.bot, update.message.chat_id)
    
    await wait_msg.delete()
    
    if response:
        print(f"[✅] تم الرد بواسطة {used}")
        await update.message.reply_text(f"🤖 **حكيم ({used}):**\n\n{response}", parse_mode="Markdown")
    else:
        print("[❌] فشلت جميع المحركات")
        await update.message.reply_text("⚠️ عذراً، المحركات الطبية مشغولة حالياً. حاول ثانية.")

# ============================================================================
# MAIN
# ============================================================================

def main():
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN missing in .env")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # الترتيب مهم جداً
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    
    print("🚀 حكيم v3.2 يعمل الآن... ابعث رسالة لتجربته!")
    app.run_polling()

if __name__ == "__main__":
    main()
