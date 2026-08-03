#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Интро-бот – публикует на личную стену ВК анонсы с ссылками на группы.
Использует Pexels для картинок, автопостинг каждые 6 часов.
Добавляет авто-комментарий под каждым постом.
"""

import os
import io
import json
import time
import logging
import random
import re
import requests
import threading
import schedule
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
import vk_api
from vk_api.upload import VkUpload

load_dotenv()

# ---------- НАСТРОЙКИ ----------
VK_TOKEN_USER = os.getenv("VK_TOKEN_USER")
VK_USER_ID = int(os.getenv("VK_USER_ID", "317272476"))
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
AGNES_API_KEY = os.getenv("AGNES_API_KEY")   # опционально, для рерайта
DATA_DIR = os.getenv("DATA_DIR", "./data")

if not VK_TOKEN_USER or not VK_USER_ID:
    raise ValueError("VK_TOKEN_USER и VK_USER_ID обязательны!")

os.makedirs(DATA_DIR, exist_ok=True)
STATE_FILE = os.path.join(DATA_DIR, "intro_state.json")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("intro_bot")

# ---------- НАСТРОЙКИ ГРУПП ----------
GROUPS = [
    {
        "name": "AI Навигатор",
        "link": "https://vk.com/ai_navigator",
        "description": "всё о нейросетях, искусственном интеллекте и технологиях будущего",
        "theme": "искусственный интеллект",
        "hashtags": "#нейросети #искусственныйинтеллект #технологии #будущее #ai"
    },
    {
        "name": "Строительный навигатор",
        "link": "https://vk.com/stroy_navigator",
        "description": "строительство, ремонт, архитектура, советы от профессионалов",
        "theme": "строительство",
        "hashtags": "#строительство #ремонт #архитектура #дом #стройматериалы"
    },
    {
        "name": "Родительский навигатор",
        "link": "https://vk.com/roditelskiy_navigator",
        "description": "воспитание, дети, образование, психология для родителей",
        "theme": "воспитание детей",
        "hashtags": "#воспитание #дети #родители #психология #семья"
    },
    {
        "name": "НейроДуша (Telegram)",
        "link": "https://t.me/neiro_dusha",
        "description": "нейросети, ИИ, мемы, инсайты — в телеграм-канале",
        "theme": "искусственный интеллект",
        "hashtags": "#нейросети #телеграм #ии #инсайты #нейродуша"
    }
]

# ---------- TELEGRAM ДЛЯ УПРАВЛЕНИЯ (опционально) ----------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_INTRO")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}" if TELEGRAM_TOKEN else None

def send_telegram_message(chat_id, text):
    if BASE_URL:
        requests.post(f"{BASE_URL}/sendMessage", json={"chat_id": chat_id, "text": text})

def get_updates(offset=None):
    if not BASE_URL:
        return []
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    return requests.get(f"{BASE_URL}/getUpdates", params=params).json().get("result", [])

# ---------- ГЕНЕРАЦИЯ ТЕКСТА ИНТРО ----------
def generate_intro(group):
    """Генерирует текст интро-поста для группы"""
    name = group["name"]
    desc = group["description"]
    link = group["link"]
    hashtags = group["hashtags"]
    theme = group["theme"]

    if AGNES_API_KEY:
        try:
            headers = {"Authorization": f"Bearer {AGNES_API_KEY}", "Content-Type": "application/json"}
            prompt = f"""
Напиши короткий интригующий пост-анонс для группы {name} (https://vk.com/{link}), где мы публикуем контент о {theme}.

Пост должен:
1. Начинаться с цепляющего заголовка (5–7 слов) с эмодзи 🔥 или 🚀.
2. Содержать 2–3 предложения, которые интригуют и привлекают внимание.
3. Заканчиваться призывом перейти в группу по ссылке.
4. Содержать вопрос к аудитории для вовлечения.
5. В конце — хештеги (5–7 штук).

Без воды, ярко, ёмко, с душой.
"""
            data = {
                "model": "agnes-v1",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300,
                "temperature": 0.8
            }
            resp = requests.post("https://apihub.agnes-ai.cn/v1/chat/completions", json=data, headers=headers, timeout=30)
            if resp.status_code == 200:
                result = resp.json()
                text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                if text and len(text) > 50:
                    logger.info(f"✅ Agnes сгенерировал интро для {name}")
                    return text.strip()
        except Exception as e:
            logger.warning(f"Agnes не сработал: {e}")

    # Резервный шаблон
    hooks = [
        f"🔥 {name.upper()} – ЭТО ТО, ЧТО ТЫ ИСКАЛ!",
        f"🚀 {name.upper()} – НОВЫЙ УРОВЕНЬ ЗНАНИЙ!",
        f"💥 {name.upper()} – ПРИСОЕДИНЯЙСЯ К НАМ!",
        f"✨ {name.upper()} – ЗДЕСЬ ВСЁ ПО ДЕЛУ!"
    ]
    hook = random.choice(hooks)

    intros = [
        f"Хочешь быть в курсе последних трендов в {theme}? Тогда тебе точно к нам!",
        f"Мы ежедневно публикуем полезный контент о {theme}. Не пропусти!",
        f"Устал от бесполезной информации? У нас – только факты и лайфхаки!"
    ]
    intro = random.choice(intros)

    call = f"➡️ Переходи и подписывайся: {link}"

    questions = [
        f"👇 {random.choice(['А ты уже подписан?', 'Что тебе интересно узнать?', 'Какую тему обсудим?'])}",
        f"👇 {random.choice(['Пиши в комментариях!', 'Ждём твоё мнение!', 'Что думаешь?'])}"
    ]
    question = random.choice(questions)

    post = f"{hook}\n\n{intro}\n\n{call}\n\n{question}\n\n{hashtags}"
    return post

# ---------- КАРТИНКИ (PEXELS) ----------
def search_pexels_photo(query):
    if not PEXELS_API_KEY:
        return None
    url = "https://api.pexels.com/v1/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": query, "per_page": 5, "orientation": "landscape"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            photos = data.get("photos", [])
            if photos:
                return random.choice(photos)["src"]["large"]
    except Exception as e:
        logger.warning(f"Pexels ошибка: {e}")
    return None

def download_photo(url):
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200:
            return resp.content
    except:
        pass
    return None

def generate_image(theme):
    if PEXELS_API_KEY:
        photo_url = search_pexels_photo(theme)
        if photo_url:
            img = download_photo(photo_url)
            if img:
                return img, "Pexels"
    # Баннер
    img = Image.new('RGB', (1024, 1024), color='#0a0a2e')
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)
    except:
        font = ImageFont.load_default()
    draw.text((50, 400), f"{theme[:20]}", fill='#FFD700', font=font)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue(), "баннер"

# ---------- ЗАГРУЗКА ФОТО НА ВК ----------
def upload_photo_to_vk_via_http(image_bytes, owner_id, token):
    try:
        vk = vk_api.VkApi(token=token)
        upload_url = vk.method('photos.getWallUploadServer', {})['upload_url']
        files = {'photo': ('image.jpg', image_bytes, 'image/jpeg')}
        resp = requests.post(upload_url, files=files)
        resp.raise_for_status()
        upload_data = resp.json()
        if 'photo' not in upload_data or 'server' not in upload_data or 'hash' not in upload_data:
            return None
        save_params = {
            'photo': upload_data['photo'],
            'server': upload_data['server'],
            'hash': upload_data['hash']
        }
        saved = vk.method('photos.saveWallPhoto', save_params)
        photo = saved[0]
        attachment = f"photo{photo['owner_id']}_{photo['id']}"
        return attachment
    except Exception as e:
        logger.error(f"Ошибка загрузки фото: {e}")
        return None

# ---------- ДОБАВЛЕНИЕ КОММЕНТАРИЯ ----------
def add_comment_to_post(post_id, comment_text):
    """Добавляет комментарий под постом на личной стене"""
    try:
        params = {
            "access_token": VK_TOKEN_USER,
            "owner_id": VK_USER_ID,
            "post_id": post_id,
            "message": comment_text,
            "v": "5.131"
        }
        resp = requests.get("https://api.vk.com/method/wall.createComment", params=params).json()
        if "error" in resp:
            logger.error(f"Ошибка комментария: {resp['error']['error_msg']}")
        else:
            logger.info(f"✅ Комментарий добавлен (id: {resp['response']['comment_id']})")
    except Exception as e:
        logger.error(f"Ошибка добавления комментария: {e}")

# ---------- ПУБЛИКАЦИЯ ИНТРО С КОММЕНТАРИЕМ ----------
def publish_intro(group):
    """Публикует интро-пост и добавляет комментарий"""
    try:
        text = generate_intro(group)
        theme = group["theme"]
        image_bytes, source = generate_image(theme)

        attachments = []
        if image_bytes:
            attachment = upload_photo_to_vk_via_http(image_bytes, VK_USER_ID, VK_TOKEN_USER)
            if attachment:
                attachments.append(attachment)
                logger.info("Фото загружено на личную стену")
            else:
                logger.warning("Не удалось загрузить фото, публикуем без фото")

        params = {
            "access_token": VK_TOKEN_USER,
            "owner_id": VK_USER_ID,
            "message": text,
            "v": "5.131"
        }
        if attachments:
            params["attachments"] = ",".join(attachments)

        resp = requests.get("https://api.vk.com/method/wall.post", params=params).json()
        if "error" in resp:
            return f"❌ Ошибка VK: {resp['error']['error_msg']}"

        post_id = resp["response"]["post_id"]
        logger.info(f"✅ Интро опубликовано для {group['name']} (id: {post_id})")

        # ----- ДОБАВЛЯЕМ АВТО-КОММЕНТАРИЙ -----
        comment_text = f"👉 Подпишись на {group['name']}, чтобы не пропустить новые посты: {group['link']}\n\n"
        comment_text += f"🔥 А также загляни в другие наши проекты:\n"
        # добавим ссылки на все группы (кроме текущей)
        for g in GROUPS:
            if g["name"] != group["name"]:
                comment_text += f"• {g['name']} – {g['link']}\n"
        comment_text += "\n👇 Ждём твоих комментариев и вопросов!"
        add_comment_to_post(post_id, comment_text)

        return f"✅ Интро для {group['name']} опубликовано + комментарий добавлен"
    except Exception as e:
        logger.error(f"Ошибка публикации: {e}")
        return f"❌ Ошибка: {e}"

# ---------- ПОЛУЧЕНИЕ СЛЕДУЮЩЕЙ ГРУППЫ ----------
def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {"last_index": -1, "date": ""}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def get_next_group():
    state = load_state()
    today = datetime.now().strftime("%Y-%m-%d")
    if state.get("date") != today:
        state["date"] = today
        state["last_index"] = -1
    next_idx = state["last_index"] + 1
    if next_idx >= len(GROUPS):
        next_idx = 0
    state["last_index"] = next_idx
    save_state(state)
    return GROUPS[next_idx]

# ---------- ПЛАНИРОВЩИК ----------
def scheduled_post():
    logger.info("⏰ Автопостинг интро (каждые 6 часов)")
    try:
        group = get_next_group()
        result = publish_intro(group)
        logger.info(f"Результат: {result}")
    except Exception as e:
        logger.error(f"Ошибка: {e}")

def scheduler_worker():
    logger.info("📡 Планировщик интро запущен (4 поста в сутки)")
    scheduled_post()
    schedule.every(6).hours.do(scheduled_post)
    while True:
        schedule.run_pending()
        time.sleep(60)

# ---------- КОМАНДЫ TELEGRAM (если есть) ----------
def handle_command(chat_id, text):
    if text == "/ping":
        send_telegram_message(chat_id, "🏓 Pong! Интро-бот работает")
        return
    if text == "/status":
        state = load_state()
        total = len(GROUPS)
        send_telegram_message(chat_id, f"📊 Сегодня опубликовано интро для {state['last_index']+1} групп из {total}.")
        return
    if text.startswith("/post"):
        content = text.replace("/post", "").strip()
        if not content:
            send_telegram_message(chat_id, "❌ Укажите тему или название группы.")
            return
        for g in GROUPS:
            if content.lower() in g["name"].lower() or content.lower() in g["theme"].lower():
                result = publish_intro(g)
                send_telegram_message(chat_id, f"📌 Результат: {result}")
                return
        send_telegram_message(chat_id, "❌ Группа не найдена.")
        return

# ---------- ЗАПУСК ----------
def main():
    logger.info("🚀 Интро-бот запущен (с авто-комментированием)")
    threading.Thread(target=scheduler_worker, daemon=True).start()

    if TELEGRAM_TOKEN:
        last_update_id = 0
        while True:
            try:
                updates = get_updates(offset=last_update_id + 1)
                if updates:
                    for update in updates:
                        last_update_id = update["update_id"]
                        if "message" in update:
                            msg = update["message"]
                            chat_id = msg["chat"]["id"]
                            if "text" in msg:
                                handle_command(chat_id, msg["text"].strip())
                time.sleep(1)
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                time.sleep(5)
    else:
        while True:
            time.sleep(60)

if __name__ == "__main__":
    main()