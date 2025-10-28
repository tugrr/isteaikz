from flask import Flask, request, abort
import requests
import os
import base64
import tempfile
import time
import hmac
import hashlib
import re
import uuid
from collections import deque
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
app = Flask(__name__)


VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OWNER_NUMBER = os.getenv("OWNER_NUMBER", "77089537431")
APP_SECRET = os.getenv("APP_SECRET", "")  


REQUIRED_ENVS = ["VERIFY_TOKEN", "WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID", "OPENAI_API_KEY"]
missing = [k for k in REQUIRED_ENVS if not os.getenv(k)]
if missing:
    raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

client = OpenAI(api_key=OPENAI_API_KEY)


MAX_TURNS = 16             
STRICT_MODE = True      
MAX_MEDIA_MB = 25          
SEEN_MSGS = deque(maxlen=5000) 
ESC_COOLDOWN = {}          
SCOPE_CACHE = {}           

# Модели
GEN_MODEL = "gpt-5"
TRANSCRIBE_MODEL = "gpt-4o-transcribe"

class Store:
    def __init__(self):
        self.sessions = {}     
        self.notified = set()
        self.last_reply = {}   

STORE = Store()


FALLBACKS = [
    "Чем помочь? Интересуют боты WhatsApp/Telegram/Instagram или интеграция с CRM?",
    "Подскажите, что автоматизировать: WhatsApp/Telegram/Instagram бот или CRM-интеграция?",
    "Готов помочь. Нужен бот (WhatsApp/Telegram/Instagram) или интеграция с amo/Bitrix/1C?"
]
OFFTOP_REPLY = (
    "Похоже, вопрос вне наших услуг. Мы занимаемся ИИ для бизнеса: "
    "чат-боты WhatsApp/Telegram, голосовые ассистенты, интеграции с amoCRM/Bitrix24/1C и автоматизация процессов. "
    "Подскажите, что хотите автоматизировать — сбор лидов, запись клиентов, напоминания, FAQ или продажи?"
)


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

def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())

def next_fallback(phone: str) -> str:
    idx = (len(STORE.sessions.get(phone, [])) // 2) % len(FALLBACKS)
    return FALLBACKS[idx]

def trim_history(hist, max_chars=8000):
    total = 0
    out = []
    for m in reversed(hist):
        total += len((m.get("content") or ""))
        out.append(m)
        if total >= max_chars:
            break
    return list(reversed(out))

def detect_lang(s: str) -> str:
    s = s or ""
    kk = re.search(r"[әіңғүқөһӘІҢҒҮҚӨҺ]", s)
    ru = re.search(r"[А-Яа-яЁё]", s)
    if kk and not ru:
        return "KK"
    if ru:
        return "RU"
    return "EN"

def is_duplicate(msg_id: str) -> bool:
    if not msg_id:
        return False
    if msg_id in SEEN_MSGS:
        return True
    SEEN_MSGS.append(msg_id)
    return False

def verify_signature(raw_body: bytes, signature: str) -> bool:

    if not APP_SECRET or not signature:
        return False
    mac = hmac.new(APP_SECRET.encode(), msg=raw_body, digestmod=hashlib.sha256)
    expected = "sha256=" + mac.hexdigest()
    return hmac.compare_digest(expected, signature)

@app.before_request
def check_meta_signature():
    if request.method == "POST" and request.path == "/webhook":
        sig = request.headers.get("X-Hub-Signature-256")
        if not verify_signature(request.data, sig):
            return abort(403)

def is_in_scope(text: str) -> bool:
    if not STRICT_MODE:
        return True
    t = _norm(text)
    now = time.time()
    hit = SCOPE_CACHE.get(t)
    if hit and now - hit[0] < 600: 
        return hit[1]


    quick_ok = any(k in t for k in ["бот", "whatsapp", "telegram", "интегра", "crm", "битрикс", "amocrm", "автоматиз", "чат-бот"])
    quick_out = any(k in t for k in ["домашнее задание", "курсова", "реферат", "медицина", "диагноз", "юридически"])
    if quick_out and not quick_ok:
        SCOPE_CACHE[t] = (now, False)
        return False


    try:
        clf = client.chat.completions.create(
            model=GEN_MODEL,
            max_completion_tokens=2,
            timeout=10,
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
                {"role": "user", "content": text[:800]}
            ]
        )
        label = (clf.choices[0].message.content or "").strip().upper()
        ok = (label == "IN")
    except Exception as e:
        print("⚠️ scope LLM fail:", e)
        ok = True

    SCOPE_CACHE[t] = (now, ok)
    return ok

def ai_chat(messages, max_tokens=450, temperature=0.3):
    try:
        resp = client.chat.completions.create(
            model=GEN_MODEL,
            messages=messages,
            max_completion_tokens=max_tokens,
            temperature=temperature,
            timeout=30
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print("❌ AI error:", e)
        return ""

def maybe_escalate(phone, client_name, text_blob):
    now = time.time()
    last = ESC_COOLDOWN.get(phone, 0)
    if now - last < 300:  # 5 минут кулдаун
        return
    hot_flags = ["созвон", "звонок", "call", "сегодня", "asap", "бюджет", "смета", "цена", "стоимость"]
    if any(f in (text_blob or "").lower() for f in hot_flags):
        if OWNER_NUMBER and OWNER_NUMBER != phone:
            notify_owner(client_number=phone, client_name=client_name)
            ESC_COOLDOWN[phone] = now

def send_whatsapp_message(to, message, retries=2):
    body = ("" if message is None else str(message)).strip() or "…"
    url = f"https://graph.facebook.com/v24.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json",
        "X-Idempotency-Key": str(uuid.uuid4())
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": body[:4000],
            "preview_url": False
        }
    }
    for i in range(retries + 1):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            print("📤 WA send:", r.status_code, r.text[:300])
            r.raise_for_status()
            return True
        except Exception as e:
            print(f"❌ Send attempt {i+1}:", e)
            time.sleep(1.2 * (i + 1))
    return False

def get_media_url(media_id):
    url = f"https://graph.facebook.com/v24.0/{media_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    res = requests.get(url, headers=headers, timeout=30)
    res.raise_for_status()
    return res.json()["url"]

def transcribe_audio(media_id):
    try:
        audio_url = get_media_url(media_id)
        r = requests.get(audio_url, headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}, timeout=30)
        r.raise_for_status()
        if len(r.content) > MAX_MEDIA_MB * 1024 * 1024:
            return "Аудио слишком большое. Пришлите короче 25 МБ."
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=True) as f:
            f.write(r.content)
            f.flush()
            with open(f.name, "rb") as audio_file:
                tr = client.audio.transcriptions.create(model=TRANSCRIBE_MODEL, file=audio_file)
        return tr.text
    except Exception as e:
        print("❌ transcribe:", e)
        return "Кешіріңіз, аудионы тану болмады. Сұрағыңызды мәтінмен жіберіңізші?"

def describe_image(media_id):
    """
    Скачиваем изображение, кодируем в base64 и просим модель кратко описать,
    мягко возвращая к бизнес-контексту при оффтопе.
    """
    try:
        img_url = get_media_url(media_id)
        resp = requests.get(img_url, headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}, timeout=30)
        resp.raise_for_status()
        mime = resp.headers.get("Content-Type", "image/jpeg")
        if not mime.startswith("image/"):
            return "Получен файл, но это не изображение."
        b64 = base64.b64encode(resp.content).decode("utf-8")
        data_url = f"data:{mime};base64,{b64}"
        response = client.chat.completions.create(
            model=GEN_MODEL,
            timeout=30,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Опиши изображение кратко, деловым тоном. Если вне ИИ/CRM — мягко верни к нашим услугам."},
                    {"type": "image_url", "image_url": {"url": data_url}}
                ]
            }]
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        print("❌ Image describe error:", e)
        return "Сурет жүктелмеді. Мәтінмен қысқаша жазыңызшы?"

def extract_user_message(value):
    msg = value["messages"][0]
    t = msg.get("type")
    if t == "text":
        return (msg.get("text", {}) or {}).get("body", "").strip()
    if t == "audio":
        return transcribe_audio(msg["audio"]["id"])
    if t == "image":
        return f"[image]\n{describe_image(msg['image']['id'])}"
    if t == "document":
        return "Получил документ. Кратко опишите, что нужно автоматизировать по нему?"
    if t == "video":
        return "Получил видео. Чем помочь по бизнес-процессам/ботам?"
    # мягкий дефолт
    return "Қайырлы күн! Қай бағыт қызықтырады: WhatsApp/Telegram бот немесе CRM интеграция?"


def notify_owner(client_number, client_name):
    text = (
        "📢 *Новый/горячий клиент*\n\n"
        f"👤 Имя: {client_name}\n"
        f"📱 Номер: +{client_number}\n"
        "💬 Написал(а) в WhatsApp ISTE AI\n"
        "➡️ Проверь диалог и, если горячий запрос, свяжись."
    )
    send_whatsapp_message(OWNER_NUMBER, text)


@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✅ Webhook verified!")
        return challenge, 200
    return "Verification failed", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    try:
        value = data["entry"][0]["changes"][0]["value"]
    except Exception:
        return "ok", 200

    messages_in = value.get("messages")
    if not messages_in:
        return "ok", 200

    message = messages_in[0]
    msg_id = message.get("id")
    if is_duplicate(msg_id):
        return "ok", 200

    phone_number = message.get("from")
    msg_type = message.get("type")
    contact = (value.get("contacts") or [{}])[0]
    client_name = (contact.get("profile") or {}).get("name", "Без имени")

    print(f"📩 WA: has message, from={phone_number}, type={msg_type}")

    if phone_number not in STORE.sessions:
        STORE.sessions[phone_number] = []
        if phone_number not in STORE.notified and OWNER_NUMBER and OWNER_NUMBER != phone_number:
            notify_owner(phone_number, client_name)
            STORE.notified.add(phone_number)

    user_message = extract_user_message(value)

    if not is_in_scope(user_message):
        send_whatsapp_message(phone_number, OFFTOP_REPLY)
        return "ok", 200


    STORE.sessions[phone_number].append({"role": "user", "content": user_message})
    STORE.sessions[phone_number] = trim_history(STORE.sessions[phone_number], max_chars=8000)


    lang = detect_lang(user_message)


    messages = [
        {"role": "system", "content": SYSTEM_RULES},
        {"role": "system", "content": ISTE_AI_KNOWLEDGE},
        {"role": "system", "content": f"Always answer in: {lang}"},
        *STORE.sessions[phone_number]
    ]
    reply = ai_chat(messages, max_tokens=450, temperature=0.3)


    if not reply:
        reply = next_fallback(phone_number)

    if _norm(STORE.last_reply.get(phone_number)) == _norm(reply):
        reply = next_fallback(phone_number)

    try:
        maybe_escalate(phone_number, client_name, (user_message or "") + " " + (reply or ""))
    except Exception as e:
        print("⚠️ Escalation check error:", e)

    STORE.sessions[phone_number].append({"role": "assistant", "content": reply})
    send_whatsapp_message(phone_number, reply)
    STORE.last_reply[phone_number] = reply

    return "ok", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

