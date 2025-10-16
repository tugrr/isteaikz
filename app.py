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

sessions = {}
notified_clients = set()

ISTE_AI_KNOWLEDGE = """
🧠 *База знаний ISTE AI*

ISTE AI — компания по внедрению искусственного интеллекта для бизнеса.
Мы создаём чат-ботов, голосовых ассистентов и системы автоматизации.

📍 Основные направления:
• 🤖 ИИ-агенты и чат-боты (WhatsApp, Telegram, сайт)
• ⚙️ Интеграции с CRM (amoCRM, Bitrix24)
• 📊 Аналитика и автоматизация
• 🧠 Обучение ИИ на данных компании

🌍 Сайт: iste-ai.kz
📞 WhatsApp: +7 708 953 74 31
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
        msg_type = message.get("type")
        contact = value.get("contacts", [{}])[0]
        client_name = contact.get("profile", {}).get("name", "Без имени")

        if phone_number not in sessions:
            sessions[phone_number] = []
            if phone_number not in notified_clients:
                notify_owner(phone_number, client_name)
                notified_clients.add(phone_number)

        # === Определяем тип входящего сообщения ===
        user_message = ""
        if msg_type == "text":
            user_message = message["text"]["body"]

        elif msg_type == "audio":  # 🎤 Голосовое сообщение
            audio_id = message["audio"]["id"]
            user_message = transcribe_audio(audio_id)

        elif msg_type == "image":  # 🖼 Фото
            image_id = message["image"]["id"]
            user_message = describe_image(image_id)

        else:
            user_message = "Мен, әзірге, бұл форматтағы хабарламаларды қабылдай алмаймын 🙂"

        sessions[phone_number].append({"role": "user", "content": user_message})

        # === Ответ от AI ===
        messages = [
            {"role": "system", "content": "Сен дружелюбный ИИ-ассистент компании ISTE AI. Говори по-казахски, по-русски или по-английски, как клиент."},
            {"role": "system", "content": ISTE_AI_KNOWLEDGE}
        ] + sessions[phone_number]

        ai_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=400
        )

        reply = ai_response.choices[0].message.content.strip()
        sessions[phone_number].append({"role": "assistant", "content": reply})
        send_whatsapp_message(phone_number, reply)

    except Exception as e:
        print("❌ Ошибка:", e)

    return "ok", 200


# === Отправка текста в WhatsApp ===
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


# === Голос в текст (Whisper) ===
def transcribe_audio(media_id):
    audio_url = get_media_url(media_id)
    audio_data = requests.get(audio_url, headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}).content
    with open("voice.ogg", "wb") as f:
        f.write(audio_data)
    audio_file = open("voice.ogg", "rb")
    transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_file)
    return transcript.text


# === Описание изображения ===
def describe_image(media_id):
    img_url = get_media_url(media_id)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Опиши это изображение кратко и дружелюбно."},
                {"type": "image_url", "image_url": {"url": img_url}}
            ]
        }]
    )
    return response.choices[0].message.content.strip()


# === Получение ссылки на медиа ===
def get_media_url(media_id):
    url = f"https://graph.facebook.com/v21.0/{media_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    res = requests.get(url, headers=headers)
    return res.json()["url"]


# === Уведомление владельца о новом клиенте ===
def notify_owner(client_number, client_name):
    owner_number = "77089537431"
    text = f"📢 *Новый клиент!* \n\n👤 Имя: {client_name}\n📱 Номер: +{client_number}\n💬 Написал впервые в WhatsApp ISTE AI"
    send_whatsapp_message(owner_number, text)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
