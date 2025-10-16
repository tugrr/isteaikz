from flask import Flask, request
import requests
import os
import base64
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
app = Flask(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OWNER_NUMBER = os.getenv("OWNER_NUMBER", "77089537431")

client = OpenAI(api_key=OPENAI_API_KEY)

# ====== Память сессий ======
sessions = {}              # {phone: [{"role": "...", "content": "..."}]}
notified_clients = set()
MAX_TURNS = 16             # обрезаем историю, чтобы не расползалась
STRICT_MODE = True         # включен off-topic сторож

# ====== База знаний (short) ======
ISTE_AI_KNOWLEDGE = """
🏢 ISTE AI — ИИ-решения под ключ для бизнеса в Казахстане
Фокус: только прикладной ИИ для компаний РК. Языки: KK/RU/EN. Тон: дружелюбный и деловой.

Что делаем:
• 🔹 ИИ-агенты (менеджеры по продажам/поддержке, рекрутеры, чат-боты)
• 🔹 Интеграции с CRM/учётом (amoCRM, Bitrix24, 1C, Google Sheets, Webhooks)
• 🔹 Полный цикл «под ключ»: аудит → пилот 1–2 недели → прод → поддержка

Принципы:
• Индивидуальный подход под нишу и KPI
• Данные клиента по NDA, доступы минимально необходимые
• Измеримость: цели, метрики, отчёты

📊 Прайс-лист (ориентировочно):
• 💬 WhatsApp-бот — создание и настройка: 100 000 ₸, ежемесячная подписка: 10 000 ₸  
• 📩 Telegram-бот — создание и настройка: 80 000 ₸, ежемесячная подписка: 8 000 ₸  
• 📷 Instagram-бот — создание и настройка: 100 000 ₸, ежемесячная подписка: 10 000 ₸  

Кому: сервисы, e-commerce, клиники (без диагностики), образование, недвижимость, b2b-услуги — **на территории Казахстана**.

Ценность:
• −20–40% нагрузки на операторов, 24/7 обработка
• +15–30% конверсия из обращений в заявки/бронь
• Быстрые ответы в мессенджерах (<1 с), устойчивость под трафик

Сбор лида (коротко, по очереди):
Имя / Компания / Город (в РК) / Ниша → Цель автоматизации → Канал (WhatsApp/Telegram/веб/голос) →
CRM (amo/Bitrix/1C/нет) → Срок запуска → Бюджет (вилка) → Контакт (WhatsApp/телега/email).

Эскалация владельцу: если «готов созвон», есть бюджет/срок «ASAP», большой трафик, VIP.
Политики: не даём мед/юрид. советов; не делаем проекты за пределами бизнес-кейсов РК; конфиденциальное — только по NDA.
Контакты: iste-ai.kz | WhatsApp: +7 708 953 74 31.
"""


# ====== Системный промпт (строгие правила тематики) ======
SYSTEM_RULES = """
Ты — ассистент ISTE AI. Отвечай на языке клиента (KK/RU/EN).
Строго держись тем:
— ИИ-решения «под ключ» для бизнеса в Казахстане
— ИИ-агенты (менеджеры, рекрутеры, боты), интеграции с CRM/учётом
— Автоматизация, аналитика, процесс внедрения, сроки, ориентиры стоимости, безопасность и работа с данными
— География: Казахстан (если клиент из другой страны — вежливо сообщи, что сейчас работаем по РК)

Если вопрос вне тематики (личные темы, учебные задания, финрынки, бытовые вопросы, программирование на заказ и т.п.)
или вне географии (за пределами РК) — вежливо откажись и мягко верни к нашим услугам в РК:
«Похоже, этот вопрос не относится к нашей сфере 🙂 Мы занимаемся ИИ-решениями для бизнеса в Казахстане. Подскажите, что вам интересно — WhatsApp/Telegram/Instagram боты или автоматизация процессов?

Бұл сұрақ біздің қызмет саламызға жатпайтын сияқты 🙂 Біз Қазақстандағы бизнеске арналған ЖИ-шешімдермен айналысамыз. Қай бағыт сізді қызықтырады — WhatsApp/Telegram/Instagram боттары ма, әлде процестерді автоматтандыру ма?»

Всегда собери краткий бриф (Имя/Компания/Город в РК/Ниша/Цель/Канал/CRM/Срок/Бюджет/Контакт) за 1–3 уточнения.
Пиши коротко, по делу, 1 явный CTA (предложи мини-бриф или созвон).
Не выдавай мед/юрид советы и конфиденциальные данные. Соблюдай NDA-тон.
"""


# ====== Классификатор тематики (IN/OUT) ======
def is_in_scope(text: str) -> bool:
    if not STRICT_MODE:
        return True
    try:
        clf = client.chat.completions.create(
            model="gpt-5",
            max_completion_tokens=2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return only IN or OUT.\n"
                        "IN: message is about BUSINESS AI for companies in KAZAKHSTAN — "
                        "AI agents (sales/support managers, recruiters, chatbots), CRM integrations, "
                        "automation, analytics, pricing, process, security, NDA, timelines.\n"
                        "OUT: personal/medical/legal advice, homework, general coding help, "
                        "consumer questions, topics not about business AI, or clearly outside Kazakhstan scope."
                    )
                },
                {"role": "user", "content": text[:1000]}
            ]
        )
        label = clf.choices[0].message.content.strip().upper()
        return label == "IN"
    except Exception:
        return True


# ====== Возврат оффтопа ======
OFFTOP_REPLY = (
    "Похоже, вопрос вне наших услуг. Мы занимаемся ИИ для бизнеса: "
    "чат-боты WhatsApp/Telegram, голосовые ассистенты, интеграции с amoCRM/Bitrix24/1C и автоматизация процессов. "
    "Подскажите, что хотите автоматизировать — сбор лидов, запись клиентов, напоминания, FAQ или продажи?"
)

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
        messages_in = value.get("messages", [])
        if not messages_in:
            return "ok", 200

        message = messages_in[0]
        phone_number = message["from"]
        msg_type = message.get("type")
        contact = value.get("contacts", [{}])[0]
        client_name = contact.get("profile", {}).get("name", "Без имени")

        # Инициализация сессии + одноразовая нотификация владельца
        if phone_number not in sessions:
            sessions[phone_number] = []
            if phone_number not in notified_clients:
                notify_owner(phone_number, client_name)
                notified_clients.add(phone_number)

        # Определяем тип входящего сообщения
        user_message = ""
        if msg_type == "text":
            user_message = message["text"]["body"]

        elif msg_type == "audio":  # 🎤 Голосовое сообщение
            audio_id = message["audio"]["id"]
            user_message = transcribe_audio(audio_id)

        elif msg_type == "image":  # 🖼 Фото
            image_id = message["image"]["id"]
            # Картинки описываем только если это по теме (например, схема/скрин CRM)
            img_desc = describe_image(image_id)
            user_message = f"[image]\n{img_desc}"

        else:
            user_message = "Мен әзірге бұл форматтағы хабарламаларды қабылдай алмаймын 🙂"

        # Off-topic фильтр
        if not is_in_scope(user_message):
            send_whatsapp_message(phone_number, OFFTOP_REPLY)
            return "ok", 200

        # Обновляем историю и обрезаем до MAX_TURNS*2 сообщений
        sessions[phone_number].append({"role": "user", "content": user_message})
        if len(sessions[phone_number]) > MAX_TURNS * 2:
            sessions[phone_number] = sessions[phone_number][-MAX_TURNS * 2:]

        # === Ответ от AI ===
        messages = [
            {"role": "system", "content": SYSTEM_RULES},
            {"role": "system", "content": ISTE_AI_KNOWLEDGE},
        ] + sessions[phone_number]

        ai_response = client.chat.completions.create(
            model="gpt-5",
            messages=messages,   # немного ниже для стабильности и «без прыжков»
            max_completion_tokens=450
        )

        reply = ai_response.choices[0].message.content.strip()

        # Триггеры эскалации (минимальные эвристики)
        hot_flags = ["созвон", "звонок", "call", "сегодня", "asap", "бюджет", "смета", "цена", "стоимость"]
        if any(flag.lower() in (user_message.lower() + " " + reply.lower()) for flag in hot_flags):
            # Короткое резюме владельцу
            notify_owner(
                client_number=phone_number,
                client_name=client_name
            )

        sessions[phone_number].append({"role": "assistant", "content": reply})
        send_whatsapp_message(phone_number, reply)

    except Exception as e:
        print("❌ Ошибка:", e)

    return "ok", 200

# === Отправка текста в WhatsApp ===
def send_whatsapp_message(to, message):
    body = ("" if message is None else str(message)).strip() or "…"  # не пустим пустую строку

    url = f"https://graph.facebook.com/v24.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body[:4000], "preview_url": False}
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        print("📤 Ответ отправлен:", r.status_code, r.text[:500])
        r.raise_for_status()
    except Exception as e:
        print("❌ Send message error:", e)



# === Голос в текст (Whisper) ===
def transcribe_audio(media_id):
    import uuid, os
    file_path = None
    try:
        audio_url = get_media_url(media_id)
        resp = requests.get(audio_url, headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}, timeout=30)
        resp.raise_for_status()
        file_path = f"voice_{uuid.uuid4().hex}.ogg"
        with open(file_path, "wb") as f:
            f.write(resp.content)
        with open(file_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_file)
        return transcript.text
    except Exception:
        return "Кешіріңіз, аудионы тану сәтсіз болды. Нақты сұрақты мәтінмен жазыңызшы?"
    finally:
        if file_path and os.path.exists(file_path):
            try: os.remove(file_path)
            except: pass


# === Описание изображения ===
def describe_image(media_id):
    try:
        img_url = get_media_url(media_id)
        resp = requests.get(img_url, headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}, timeout=30)
        resp.raise_for_status()
        mime = resp.headers.get("Content-Type", "image/jpeg") or "image/jpeg"
        if not mime.startswith("image/"):
            mime = "image/jpeg"
        b64 = base64.b64encode(resp.content).decode("utf-8")
        data_url = f"data:{mime};base64,{b64}"

        response = client.chat.completions.create(
            model="gpt-5",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Опиши изображение кратко и деловым тоном. Если не связано с ИИ/CRM/автоматизацией — вежливо отметь, что это вне темы."},
                    {"type": "image_url", "image_url": {"url": data_url}}
                ]
            }],
            max_completion_tokens=150
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        print("❌ Image describe error:", e)
        return "Сурет жүктелмеді. Сипаттаманы мәтінмен жібере аласыз ба?"



# === Получение ссылки на медиа ===
def get_media_url(media_id):
    url = f"https://graph.facebook.com/v24.0/{media_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    res = requests.get(url, headers=headers)
    res.raise_for_status()
    return res.json()["url"]

# === Уведомление владельца о новом клиенте/эскалации ===
def notify_owner(client_number, client_name):
    text = (
        "📢 *Новый/горячий клиент*\n\n"
        f"👤 Имя: {client_name}\n"
        f"📱 Номер: +{client_number}\n"
        "💬 Написал(а) в WhatsApp ISTE AI\n"
        "➡️ Проверь диалог и, если горячий запрос, свяжись."
    )
    send_whatsapp_message(OWNER_NUMBER, text)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)




