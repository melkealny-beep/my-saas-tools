import os
import logging
import httpx
import csv
import random
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID") # تأكد أنه الـ ID الرقمي وليس رقم الهاتف

# ملف الإكسيل (CSV)
EXCEL_FILE = "clinic_bookings.csv"

# إنشاء ملف الإكسيل إذا لم يكن موجوداً
if not os.path.exists(EXCEL_FILE):
    with open(EXCEL_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["رقم الحجز", "الاسم", "التاريخ", "التوقيت", "بيانات المريض"])

def save_to_excel(booking_id, name, details):
    with open(EXCEL_FILE, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        now = datetime.now()
        writer.writerow([booking_id, name, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), details])

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user
    
    # منطق الحجز التلقائي
    if any(k in text for k in ["حجز", "اسم", "رقم"]):
        booking_id = random.randint(1000, 9999) # توليد رقم حجز عشوائي
        
        # 1. حفظ في ملف الإكسيل
        save_to_excel(booking_id, user.first_name, text)
        
        # 2. إرسال تأكيد للمريض
        confirmation = f"✅ تم استلام طلب الحجز بنجاح يا {user.first_name}.\n🎫 رقم الحجز المبدئي: #{booking_id}\n📍 سيتم التواصل معكم لتأكيد الموعد النهائي."
        await update.message.reply_text(confirmation)
        
        # 3. إرسال البيانات فوراً للمسؤول (الرقم اللي حددته)
        if ADMIN_ID:
            admin_msg = f"🔔 **حجز جديد في العيادة**\n\n🎫 رقم الحجز: {booking_id}\n👤 المريض: {user.first_name}\n📱 البيانات المستلمة: {text}\n📅 التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            try:
                await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg)
            except Exception as e:
                print(f"Error sending to admin: {e}")
        return

    # باقي الردود الطبية (استدعاء المحرك الذكي كما في v3.5)
    # ... (تكملة الكود الخاص بـ MedicalEngine و Groq كما هو)
