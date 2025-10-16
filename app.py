from flask import Flask, request
import requests
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
app = Flask(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

# Память для диалогов и уведомлений
sessions = {}
notified_clients = set()  # сюда сохраняем номера, которым уже отправили уведомление

# === 📘 БАЗА ЗНАНИЙ ISTE AI ===
ISTE_AI_KNOWLEDGE = """
🧠 *База знаний ISTE AI*

✨ 1. Компания  
ISTE AI — занимается разработкой и внедрением искусственного интеллекта (ИИ) для бизнеса.  
Мы создаём умных ИИ-агентов, чат-ботов и автоматизированные решения, которые помогают компаниям:  
• 💼 экономить время  
• 🤝 улучшать обслуживание клиентов  
• ⚙️ оптимизировать процессы  
• 📈 повышать продажи и эффективность

👋 2. Представление  
Если спрашивают “Кто вы?” или “Что такое ISTE AI?”, отвечай:  
_«Я виртуальный помощник компании ISTE AI. Мы разрабатываем и внедряем ИИ-агентов и автоматизированные решения для бизнеса — чат-ботов, голосовых ассистентов и системы аналитики. Помогаем компаниям экономить время и повышать эффективность.»_

🚀 3. Основные направления  
• 🤖 ИИ-агенты и чат-боты (WhatsApp, Telegram, Instagram, сайт)  
• 💬 Поддержка клиентов, заявки, FAQ  
• 🔗 Интеграции с CRM (Bitrix, amoCRM, Notion, Google Sheets)  
• 📊 Аналитика и автоматизация бизнес-процессов  
• 🧠 Обучение ИИ на данных компании  
• 🧩 Персонализированные решения под клиента

💡 4. Технологии  
GPT-5, GPT-4, Claude, Gemini, LLaMA, LangChain, RAG, FAISS, FastAPI, Node.js, Python

📦 5. Примеры проектов  
ИИ-агенты для WhatsApp и Telegram, которые:  
• создают заказы в CRM;  
• проводят собеседования для HR;  
• формируют ежедневные отчёты;  
• консультируют покупателей в онлайн-магазинах.

🔒 6. Безопасность  
Все данные клиентов обрабатываются безопасно.  
Используем шифрование и защищённые серверы.  
ИИ-агенты ISTE AI не передают личную информацию третьим лицам.

📞 7. Контакты  
📧 Email: support@iste-ai.com  
📱 WhatsApp: +7 708 953 74 31  
🌐 Сайт: iste-ai.kz

🗣️ 8. Тон общения  
Общайся дружелюбно 😊, уверенно 💬 и по делу ✅  
Подстраивайся под пользователя — проще с людьми, формально с бизнесом.
"""

# === Проверка вебхука ===
@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✅ Webhook verified!")
        return challenge, 200
    return "Verification failed", 403


# === Обработка сообщений ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("📩 Получены данные:", data)

    try:
        value = data["entry"][0]["changes"][0]["value"]
        message = value["messages"][0]
        phone_number = message["from"]
        text = message["text"]["body"]

        # имя клиента, если есть
        contact = value.get("contacts", [{}])[0]
        client_name = contact.get("profile", {}).get("name", "Без имени")

        # сохраняем историю общения
        if phone_number not in sessions:
            sessions[phone_number] = []

        sessions[phone_number].append({"role": "user", "content": text})

        # === Генерация ответа от AI ===
        messages = [
            {
                "role": "system",
                "content": (
                    "Ты — дружелюбный, профессиональный виртуальный помощник компании ISTE AI. "
                    "Отвечай кратко, понятно и по делу, используя корпоративный стиль и базу знаний:\n\n"
                    + ISTE_AI_KNOWLEDGE
                )
            }
        ] + sessions[phone_number]

        ai_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.6,
            max_tokens=400
        )

        reply = ai_response.choices[0].message.content.strip()
        sessions[phone_number].append({"role": "assistant", "content": reply})

        # === Отправляем ответ клиенту ===
        send_whatsapp_message(phone_number, reply)

        # === Уведомляем владельца, если клиент новый ===
        if phone_number not in notified_clients:
            notify_owner(phone_number, client_name)
            notified_clients.add(phone_number)

    except Exception as e:
        print("❌ Ошибка:", e)

    return "ok", 200


# === Функция отправки сообщений в WhatsApp ===
def send_whatsapp_message(to, message):
    url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    response = requests.post(url, headers=headers, json=payload)
    print("📤 Ответ отправлен:", response.status_code, response.text)


# === Уведомление владельца о новом клиенте ===
def notify_owner(client_number, client_name):
    owner_number = "77089537431"
    text = f"📢 *Новый клиент!* \n\n👤 Имя: {client_name}\n📱 Номер: +{client_number}\n\n💬 Написал впервые в WhatsApp ISTE AI"
    send_whatsapp_message(owner_number, text)


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


