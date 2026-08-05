#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Интро-бот:
- Для AI, строительного, родительского навигаторов: по 1 анонсу в день (по очереди, каждые 6 часов).
- Для музыкального навигатора: анонс на КАЖДЫЙ новый пост в его группе, с картинкой из поста.
Авто-комментарий со ссылками на все группы.
Кэш использованных картинок предотвращает дубли.
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
import hashlib
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
AGNES_API_KEY = os.getenv("AGNES_API_KEY")
PIXAZO_API_KEY = os.getenv("PIXAZO_API_KEY")
POLLINATIONS_BASE_URL = os.getenv("POLLINATIONS_BASE_URL", "https://image.pollinations.ai")
DATA_DIR = os.getenv("DATA_DIR", "./data")

if not VK_TOKEN_USER or not VK_USER_ID:
    raise ValueError("VK_TOKEN_USER и VK_USER_ID обязательны!")

os.makedirs(DATA_DIR, exist_ok=True)
STATE_FILE = os.path.join(DATA_DIR, "intro_state.json")
USED_IMAGES_FILE = os.path.join(DATA_DIR, "used_images.json")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("intro_bot")

# ---------- КЭШ КАРТИНОК ----------
def load_used_images():
    if os.path.exists(USED_IMAGES_FILE):
        with open(USED_IMAGES_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_used_images(used_set):
    with open(USED_IMAGES_FILE, "w") as f:
        json.dump(list(used_set), f)

def compute_hash(image_bytes):
    return hashlib.md5(image_bytes).hexdigest()

def is_image_used(image_bytes):
    h = compute_hash(image_bytes)
    used = load_used_images()
    return h in used

def mark_image_as_used(image_bytes):
    h = compute_hash(image_bytes)
    used = load_used_images()
    used.add(h)
    save_used_images(used)

# ---------- ГРУППЫ ----------
STANDARD_GROUPS = [
    {
        "name": "AI Навигатор",
        "link": "https://vk.com/ai_navigator",
        "theme": "искусственный интеллект",
        "hashtags": "#нейросети #искусственныйинтеллект #технологии #будущее #ai",
        "group_id": None
    },
    {
        "name": "Строительный навигатор",
        "link": "https://vk.com/stroy_navigator",
        "theme": "строительство",
        "hashtags": "#строительство #ремонт #архитектура #дом #стройматериалы",
        "group_id": None
    },
    {
        "name": "Родительский навигатор",
        "link": "https://vk.com/roditelskiy_navigator",
        "theme": "воспитание детей",
        "hashtags": "#воспитание #дети #родители #психология #семья",
        "group_id": None
    }
]

MUSIC_GROUP = {
    "name": "Музыкальный навигатор",
    "link": "https://vk.com/music_navigator",
    "theme": "музыка и творчество",
    "hashtags": "#музыка #творчество #музыканты #песни #развитие",
    "group_id": 240656847   # публичная страница
}

ALL_GROUPS = STANDARD_GROUPS + [MUSIC_GROUP]

# ---------- TELEGRAM ДЛЯ УПРАВЛЕНИЯ ----------
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
    try:
        resp = requests.get(f"{BASE_URL}/getUpdates", params=params, timeout=(15, 120))
        return resp.json().get("result", [])
    except Exception as e:
        logger.error(f"Ошибка получения обновлений: {e}")
        return []

# ---------- ГЕНЕРАЦИЯ ТЕКСТА ИНТРО ----------
def generate_intro(group, post_text=None):
    name = group["name"]
    link = group["link"]
    hashtags = group["hashtags"]
    theme = group["theme"]

    if post_text:
        teaser = post_text[:100].strip()
        if len(post_text) > 100:
            teaser += "..."
    else:
        teaser = f"контент о {theme}"

    if AGNES_API_KEY:
        try:
            headers = {"Authorization": f"Bearer {AGNES_API_KEY}", "Content-Type": "application/json"}
            prompt = f"""
Напиши короткий интригующий пост-анонс для группы {name} ({link}), где недавно появился пост: "{teaser}".

Пост должен:
1. Начинаться с цепляющего заголовка (5–7 слов) с эмодзи 🔥 или 🚀.
2. Содержать 2–3 предложения, которые интригуют и привлекают внимание к этому посту.
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
        f"💥 {name.upper()} – ПРИСОЕДИНЯЙСЯ К НАМ!"
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

# ---------- ПОЛУЧЕНИЕ КАРТИНКИ ИЗ ПОСТА ГРУППЫ ----------
def get_post_image_by_id(group_id, post_id):
    try:
        params = {
            "access_token": VK_TOKEN_USER,
            "owner_id": group_id,
            "posts": f"{group_id}_{post_id}",
            "v": "5.131"
        }
        resp = requests.get("https://api.vk.com/method/wall.getById", params=params).json()
        if "error" in resp:
            logger.warning(f"Ошибка wall.getById: {resp['error']['error_msg']}")
            return None
        posts = resp.get("response", [])
        if not posts:
            return None
        post = posts[0]
        attachments = post.get("attachments", [])
        for att in attachments:
            if att.get("type") == "photo":
                sizes = att.get("photo", {}).get("sizes", [])
                if sizes:
                    sorted_sizes = sorted(sizes, key=lambda x: x.get("width", 0) * x.get("height", 0))
                    if sorted_sizes:
                        return sorted_sizes[-1].get("url")
        return None
    except Exception as e:
        logger.error(f"Ошибка получения фото из поста: {e}")
        return None

def get_last_post(group_id):
    try:
        params = {
            "access_token": VK_TOKEN_USER,
            "owner_id": group_id,
            "count": 1,
            "v": "5.131"
        }
        resp = requests.get("https://api.vk.com/method/wall.get", params=params).json()
        if "error" in resp:
            logger.warning(f"Ошибка wall.get: {resp['error']['error_msg']}")
            return None
        items = resp.get("response", {}).get("items", [])
        if not items:
            return None
        post = items[0]
        return {
            "id": post["id"],
            "text": post.get("text", "")
        }
    except Exception as e:
        logger.error(f"Ошибка получения последнего поста: {e}")
        return None

# ---------- ГЕНЕРАТОРЫ КАРТИНОК (с кэшем и рандомизацией) ----------
def generate_agnes_image(prompt):
    if not AGNES_API_KEY:
        return None
    try:
        seed = random.randint(1, 1000000)
        # Добавляем случайные красивые слова для разнообразия
        adjectives = ["bright", "colorful", "vibrant", "modern", "elegant", "minimalistic", "professional", "high quality"]
        adj = random.choice(adjectives)
        full_prompt = f"{adj} illustration about {prompt}, creative, modern, no people, no nature"
        headers = {"Authorization": f"Bearer {AGNES_API_KEY}", "Content-Type": "application/json"}
        data = {
            "prompt": full_prompt,
            "negative_prompt": "ugly, deformed, blurry, low quality, people, human, woman, girl, nature, trees, landscape",
            "width": 1024,
            "height": 1024,
            "num_inference_steps": 30,
            "guidance_scale": 7.0,
            "seed": seed
        }
        resp = requests.post("https://apihub.agnes-ai.cn/v1/images/generations", json=data, headers=headers, timeout=30)
        if resp.status_code == 200:
            result = resp.json()
            image_url = result.get("data", [{}])[0].get("url")
            if image_url:
                img_resp = requests.get(image_url, timeout=30)
                if img_resp.status_code == 200:
                    return img_resp.content
    except Exception as e:
        logger.warning(f"Agnes генерация не сработала: {e}")
    return None

def generate_pixazo_image(prompt):
    if not PIXAZO_API_KEY:
        return None
    try:
        seed = random.randint(1, 1000000)
        adjectives = ["bright", "colorful", "vibrant", "modern", "elegant", "minimalistic", "professional", "high quality"]
        adj = random.choice(adjectives)
        full_prompt = f"{adj} illustration about {prompt}, creative, modern, no people, no nature"
        url = "https://api.pixazo.com/v1/generate"
        headers = {
            "Authorization": f"Bearer {PIXAZO_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "prompt": full_prompt,
            "model": "flux",
            "width": 1024,
            "height": 1024,
            "num_inference_steps": 30,
            "guidance_scale": 7.0,
            "seed": seed
        }
        resp = requests.post(url, json=data, headers=headers, timeout=60)
        if resp.status_code == 200:
            result = resp.json()
            image_url = result.get("image_url")
            if image_url:
                img_resp = requests.get(image_url, timeout=30)
                if img_resp.status_code == 200:
                    return img_resp.content
    except Exception as e:
        logger.warning(f"Pixazo не сработал: {e}")
    return None

def generate_pollinations_image(prompt):
    try:
        seed = random.randint(1, 1000000)
        adjectives = ["bright", "colorful", "vibrant", "modern", "elegant", "minimalistic", "professional", "high quality"]
        adj = random.choice(adjectives)
        full_prompt = f"{adj} {prompt}, creative, modern, no people, no nature"
        url = f"{POLLINATIONS_BASE_URL}/prompt/{requests.utils.quote(full_prompt)}?width=1024&height=1024&nologo=true&seed={seed}&model=flux"
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200:
            return resp.content
    except Exception as e:
        logger.warning(f"Pollinations не сработал: {e}")
    return None

def search_pexels_photo(theme):
    if not PEXELS_API_KEY:
        return None
    # Разнообразим запросы
    queries = [theme, f"{theme} abstract", f"{theme} creative", f"{theme} modern"]
    random.shuffle(queries)
    url = "https://api.pexels.com/v1/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": queries[0], "per_page": 3, "orientation": "landscape"}
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

def generate_image(group, post_id=None):
    """
    Генерирует уникальную картинку для анонса.
    Если передан post_id – пробует взять из поста.
    Иначе генерирует через нейросети с проверкой на дубли.
    """
    # 1. Пробуем взять из поста (если есть post_id)
    if post_id and group.get("group_id"):
        img_url = get_post_image_by_id(group["group_id"], post_id)
        if img_url:
            img = download_photo(img_url)
            if img:
                # Из поста не проверяем на дубли – она точно уникальна для этого поста
                mark_image_as_used(img)
                logger.info(f"✅ Картинка взята из поста {post_id} группы {group['name']}")
                return img, "из поста группы"

    # 2. Генерация через нейросети (с проверкой на дубли)
    theme = group["theme"]
    generators = [
        ("Agnes", generate_agnes_image),
        ("Pixazo", generate_pixazo_image),
        ("Pollinations", generate_pollinations_image)
    ]
    random.shuffle(generators)

    for name, func in generators:
        img = func(theme)
        if img:
            if not is_image_used(img):
                mark_image_as_used(img)
                logger.info(f"✅ Картинка сгенерирована через {name} для {group['name']} (уникальная)")
                return img, name
            else:
                logger.info(f"⚠️ Картинка от {name} уже использовалась, пробуем следующий генератор")

    # 3. Pexels (с проверкой на дубли)
    photo_url = search_pexels_photo(theme)
    if photo_url:
        img = download_photo(photo_url)
        if img and not is_image_used(img):
            mark_image_as_used(img)
            logger.info(f"✅ Картинка от Pexels для {group['name']} (уникальная)")
            return img, "Pexels"
        elif img:
            logger.info("⚠️ Картинка от Pexels уже использовалась")

    # 4. Баннер (всегда уникален, так как содержит тему)
    img = create_banner(theme)
    if not is_image_used(img):
        mark_image_as_used(img)
        logger.info(f"✅ Использован баннер для {group['name']} (уникальный)")
        return img, "баннер"
    else:
        # Если баннер совпал (маловероятно), добавляем суффикс
        img = create_banner(theme + " " + str(random.randint(1, 100)))
        mark_image_as_used(img)
        logger.info(f"✅ Использован баннер с суффиксом для {group['name']}")
        return img, "баннер"

def create_banner(theme):
    img = Image.new('RGB', (1024, 1024), color='#0a0a2e')
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)
    except:
        font = ImageFont.load_default()
    draw.text((50, 400), f"{theme[:20]}", fill='#FFD700', font=font)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()

# ---------- ЗАГРУЗКА ФОТО ----------
def upload_photo_to_vk_via_vkapi(image_bytes, owner_id, token):
    temp_path = None
    try:
        temp_path = f"/tmp/temp_{random.randint(1, 1000000)}.jpg"
        with open(temp_path, "wb") as f:
            f.write(image_bytes)

        vk = vk_api.VkApi(token=token)
        upload = VkUpload(vk)
        photo = upload.photo_wall(temp_path)
        attachment = f"photo{photo[0]['owner_id']}_{photo[0]['id']}"
        logger.info(f"Фото загружено, attachment: {attachment}")
        return attachment
    except Exception as e:
        logger.error(f"Ошибка загрузки фото: {e}")
        return None
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

# ---------- ПУБЛИКАЦИЯ АНОНСА ----------
def publish_intro(group, post_id=None, post_text=None):
    try:
        text = generate_intro(group, post_text)
        image_bytes, source = generate_image(group, post_id)

        attachments = []
        if image_bytes:
            attachment = upload_photo_to_vk_via_vkapi(image_bytes, VK_USER_ID, VK_TOKEN_USER)
            if attachment:
                attachments.append(attachment)
                logger.info(f"Фото загружено на личную стену (источник: {source})")
            else:
                logger.warning("Не удалось загрузить фото, публикуем без фото")
        else:
            logger.warning("Нет байтов изображения, публикуем без фото")

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

        post_id_vk = resp["response"]["post_id"]
        logger.info(f"✅ Интро опубликовано для {group['name']} (id: {post_id_vk})")

        comment_text = f"👉 Подпишись на {group['name']}, чтобы не пропустить новые посты: {group['link']}\n\n"
        comment_text += "🔥 А также загляни в другие наши проекты:\n"
        for g in ALL_GROUPS:
            if g["name"] != group["name"]:
                comment_text += f"• {g['name']} – {g['link']}\n"
        comment_text += "\n👇 Ждём твоих комментариев и вопросов!"
        add_comment_to_post(post_id_vk, comment_text)

        return f"✅ Интро для {group['name']} опубликовано + комментарий добавлен"
    except Exception as e:
        logger.error(f"Ошибка публикации: {e}")
        return f"❌ Ошибка: {e}"

def add_comment_to_post(post_id, comment_text):
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

# ---------- УПРАВЛЕНИЕ СОСТОЯНИЕМ ----------
def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {"last_index": -1, "date": "", "music_last_post_id": 0}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

# ---------- ПЛАНИРОВЩИК ДЛЯ СТАНДАРТНЫХ ГРУПП ----------
def scheduled_standard_post():
    logger.info("⏰ Плановый анонс для стандартной группы (каждые 6 часов)")
    state = load_state()
    today = datetime.now().strftime("%Y-%m-%d")
    if state.get("date") != today:
        state["date"] = today
        state["last_index"] = -1
    next_idx = state["last_index"] + 1
    if next_idx >= len(STANDARD_GROUPS):
        next_idx = 0
    state["last_index"] = next_idx
    save_state(state)
    group = STANDARD_GROUPS[next_idx]
    result = publish_intro(group)
    logger.info(f"Результат для {group['name']}: {result}")

def standard_scheduler_worker():
    logger.info("📡 Планировщик для стандартных групп запущен (4 поста в сутки)")
    scheduled_standard_post()
    schedule.every(6).hours.do(scheduled_standard_post)
    while True:
        schedule.run_pending()
        time.sleep(60)

# ---------- МОНИТОРИНГ МУЗЫКАЛЬНОЙ ГРУППЫ ----------
def monitor_music_group():
    logger.info("🎵 Мониторинг музыкальной группы запущен")
    while True:
        try:
            state = load_state()
            last_id = state.get("music_last_post_id", 0)
            group_id = MUSIC_GROUP["group_id"]
            post_info = get_last_post(group_id)
            if post_info:
                logger.info(f"Текущий последний пост в музыкальной группе: id={post_info['id']}, last_id={last_id}")
                if post_info["id"] != last_id:
                    logger.info(f"🎵 Обнаружен новый пост в музыкальной группе: {post_info['id']}")
                    result = publish_intro(MUSIC_GROUP, post_id=post_info["id"], post_text=post_info["text"])
                    logger.info(f"Результат анонса для музыкальной группы: {result}")
                    state["music_last_post_id"] = post_info["id"]
                    save_state(state)
                else:
                    logger.info("Новых постов в музыкальной группе нет")
            else:
                logger.warning("Не удалось получить последний пост из музыкальной группы (возможно, нет постов или нет доступа)")
            time.sleep(600)  # проверка каждые 10 минут
        except Exception as e:
            logger.error(f"Ошибка в мониторинге музыкальной группы: {e}")
            time.sleep(600)

# ---------- TELEGRAM-КОМАНДЫ ----------
def handle_command(chat_id, text):
    if text == "/ping":
        send_telegram_message(chat_id, "🏓 Pong! Интро-бот работает")
        return
    if text == "/status":
        state = load_state()
        total = len(STANDARD_GROUPS)
        used = state.get("last_index", -1) + 1
        send_telegram_message(chat_id, f"📊 Сегодня опубликовано анонсов для {used} из {total} стандартных групп.\n🎵 Последний обработанный пост в музыкальной группе: {state.get('music_last_post_id', 0)}")
        return
    if text.startswith("/post"):
        content = text.replace("/post", "").strip()
        if not content:
            send_telegram_message(chat_id, "❌ Укажите тему или название группы.")
            return
        for g in ALL_GROUPS:
            if content.lower() in g["name"].lower() or content.lower() in g["theme"].lower():
                result = publish_intro(g)
                send_telegram_message(chat_id, f"📌 Результат: {result}")
                return
        send_telegram_message(chat_id, "❌ Группа не найдена.")
        return

# ---------- ЗАПУСК ----------
def main():
    logger.info("🚀 Интро-бот запущен (с кэшем картинок и мониторингом)")
    threading.Thread(target=standard_scheduler_worker, daemon=True).start()
    threading.Thread(target=monitor_music_group, daemon=True).start()

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