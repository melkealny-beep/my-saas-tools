import os
import logging
import httpx
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID")

# روابط المحركات
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

def get_knowledge():
    if os.path.exists("knowledge.txt"):
        with open("knowledge.txt", "r", encoding="utf-8") as f:
            return f.read()
    return ""

class MedicalEngine:
    async def get_response(self, query: str, mode: str, bot, chat_id: int):
        local_info = get_knowledge()
        
        # تخصيص البرومبت بناءً على نوع الرسالة (استشارة أو حجز)
        if mode == "booking":
            instruction = "المريض يريد الحجز. اذكر له المواعيد وأيام العمل وطرق الدفع واطلب بياناته (الاسم ورقم الهاتف) بناءً على المرجع."
        else:
            instruction = "المريض يطلب استشارة طبية. حلل شكواه بناءً على تخصص دكتور أحمد سمير (كبد وباطنة وجهاز هضمي) وقدم نصائح أولية من المرجع."

        full_prompt = f"المرجع:\n{local_info}\n\nالتعليمات: {instruction}\n\nسؤال المريض: {query}"

        # محاولة الرد عبر Groq
        try:
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "system", "content": "أنت مساعد دكتور أحمد سمير عبد الحميد."}, {"role": "user", "content": full_prompt}]
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(GROQ_URL, json=payload, headers=headers)
                if r.status_code == 200: return r.json()['choices'][0]['message']['content']
        except: pass
        return "عذراً، المحرك غير متاح حالياً."

engine = MedicalEngine()

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    user = update.effective_user

    # تحديد نوع الرسالة بناءً على الكلمات المفتاحية
    if any(k in text for k in ["حجز", "احجز", "موعد", "ميعاد"]):
        mode = "booking"
        # تنبيه الأدمن بطلب حجز
        if ADMIN_ID:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"🚨 طلب حجز من {user.first_name}:\n{text}")
    elif any(k in text for k in ["استشاره", "استشارة", "تعبان", "شكوى", "وجع"]):
        mode = "consulting"
    else:
        mode = "general"

    wait_msg = await update.message.reply_text("🤔 جاري معالجة طلبك...")
    response = await engine.get_response(text, mode, context.bot, update.message.chat_id)
    await wait_msg.delete()
    await update.message.reply_text(response)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("🏥 عيادة د. أحمد سمير عبد الحميد ترحب بك. كيف يمكنني مساعدتك؟")))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    print("🚀 حكيم v3.5 يعمل الآن...")
    app.run_polling()

if __name__ == "__main__":
    main()
