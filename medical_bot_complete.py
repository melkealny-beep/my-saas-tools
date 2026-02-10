#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import logging
import httpx
import csv
import random
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction

# إعدادات التسجيل
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID") # الأدمين الأساسي من ملف .env

# ضع هنا الـ User ID الذي حصلت عليه للرقم 01121173835
RECEPTIONIST_USER_ID = "7786956319" 

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
EXCEL_FILE = "clinic_bookings.csv"

# تجهيز ملف الإكسيل
if not os.path.exists(EXCEL_FILE):
    with open(EXCEL_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["رقم الحجز", "الاسم", "التاريخ", "التوقيت", "البيانات المستلمة"])

def get_knowledge():
    if os.path.exists("knowledge.txt"):
        with open("knowledge.txt", "r", encoding="utf-8") as f:
            return f.read()
    return "عيادة د. أحمد سمير عبد الحميد - استشاري الكبد والجهاز الهضمي."

class MedicalEngine:
    async def get_response(self, query: str, mode: str):
        local_info = get_knowledge()
        prompt = f"المرجع للعيادة:\n{local_info}\n\nالوضع الحالي: {mode}\nسؤال المريض: {query}"
        try:
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": "أنت مساعد د. أحمد سمير. أجب باحترافية بناءً على المرجع."},
                    {"role": "user", "content": prompt}
                ]
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(GROQ_URL, json=payload, headers=headers)
                if r.status_code == 200:
                    return r.json()['choices'][0]['message']['content']
        except Exception as e:
            logger.error(f"AI Error: {e}")
        return "شكراً لتواصلك. يرجى تزويدنا بالاسم ورقم الهاتف للحجز."

engine = MedicalEngine()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [["🏥 حجز موعد"], ["📍 استشارة طبية"]]
    await update.message.reply_text(
        "🏥 أهلاً بك في عيادة د. أحمد سمير عبد الحميد.\nاستشاري أمراض الكبد والجهاز الهضمي والمناظير.\nكيف يمكنني مساعدتك؟",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user
    
    # تحديد إذا كان الطلب حجز
    is_booking = any(k in text for k in ["حجز", "احجز", "اسم", "رقم", "موعد"])
    mode = "booking" if is_booking else "consultation"

    booking_id = None
    if is_booking:
        booking_id = random.randint(1000, 9999)
        # 1. الحفظ في الإكسيل
        with open(EXCEL_FILE, 'a', newline='', encoding='utf-8-sig') as f:
            csv.writer(f).writerow([booking_id, user.full_name, datetime.now().strftime("%Y-%m-%d"), datetime.now().strftime("%H:%M"), text])
        
        # 2. إعداد رسالة التنبيه للموظف والأدمين
        alert_msg = (f"🚨 **طلب حجز جديد**\n"
                     f"🎫 رقم الحجز: #{booking_id}\n"
                     f"👤 المريض: {user.full_name}\n"
                     f"📱 البيانات: {text}\n"
                     f"⏰ الوقت: {datetime.now().strftime('%H:%M')}")
        
        # إرسال التنبيهات
        targets = [ADMIN_ID, RECEPTIONIST_USER_ID]
