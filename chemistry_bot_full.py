# -*- coding: utf-8 -*-
"""
Обучающий Telegram-бот по химии — полная версия с разделами.

КАК ЗАПУСТИТЬ:
1. pip install python-telegram-bot
   (для "Спросить у ИИ" ничего дополнительно ставить не нужно — используется
   прямой запрос к серверу Gemini)
2. Вставьте токен бота (от @BotFather) в TOKEN ниже.
3. Для "Спросить у ИИ" вставьте ключ Gemini в GEMINI_API_KEY
   (получить бесплатно: aistudio.google.com/apikey). Если ключа нет —
   просто не трогайте, остальной бот будет работать без этого раздела.
4. Запустите: python chemistry_bot_full.py

КАК ДОБАВЛЯТЬ РЕАЛЬНЫЙ КОНТЕНТ:
Сейчас в лекциях/видеоуроках/задачах по каждой теме стоит заготовка-плейсхолдер.
Чтобы вставить настоящий текст лекции, ссылку на видео или задачи —
найдите словарь CONTENT ниже и добавьте туда запись по образцу в комментариях.
"""

import asyncio
import json
import os
import random
import threading
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# Если бот запущен на хостинге (Render и т.п.), токен и ключ берутся из переменных
# окружения BOT_TOKEN / GEMINI_KEY. Если их нет — используются значения ниже (для Pydroid).
TOKEN = os.environ.get("BOT_TOKEN", "ВАШ_ТОКЕН_ОТ_BOTFATHER")
GEMINI_API_KEY = os.environ.get("GEMINI_KEY", "ВАШ_КЛЮЧ_GEMINI")  # aistudio.google.com/apikey

# Только этот Telegram ID может добавлять/удалять материалы.
# Узнать свой ID: напишите /start боту @userinfobot в Telegram.
# Можно также задать через переменную окружения ADMIN_ID (например, на Render).
try:
    ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0


def is_admin(user_id):
    return ADMIN_ID != 0 and user_id == ADMIN_ID

STORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "content_store.json")

# Облачное хранение (jsonbin.io) — чтобы материалы не терялись при передеплое на Render.
# Если переменные не заданы, используется обычный локальный файл (подходит для Pydroid).
JSONBIN_API_KEY = os.environ.get("JSONBIN_API_KEY", "")
JSONBIN_BIN_ID = os.environ.get("JSONBIN_BIN_ID", "")
_USE_CLOUD_STORE = bool(JSONBIN_API_KEY and JSONBIN_BIN_ID)


def load_store():
    if _USE_CLOUD_STORE:
        try:
            url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest"
            req = urllib.request.Request(url, headers={"X-Master-Key": JSONBIN_API_KEY})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            record = data.get("record", {})
            print(f"✅ Загружено из облака (jsonbin): {len(record)} ключей — {list(record.keys())}")
            return record
        except Exception as e:
            print(f"⚠ Не удалось загрузить облачное хранилище: {e}")
            return {}
    if os.path.exists(STORE_FILE):
        try:
            with open(STORE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_store():
    if _USE_CLOUD_STORE:
        try:
            url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"
            payload = json.dumps(STORE).encode("utf-8")
            req = urllib.request.Request(
                url, data=payload, method="PUT",
                headers={"X-Master-Key": JSONBIN_API_KEY, "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15):
                pass
            print(f"✅ Сохранено в облако (jsonbin): {len(STORE)} ключей — {list(STORE.keys())}")
        except Exception as e:
            print(f"⚠ Не удалось сохранить в облачное хранилище: {e}")
        return
    with open(STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(STORE, f, ensure_ascii=False, indent=2)


def call_gemini(question):
    """Прямой запрос к Gemini API без сторонних библиотек (работает в Pydroid без компиляции)."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
    )
    prompt = f"Ты — помощник по химии. Ответь кратко, понятно и по делу: {question}"
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 500},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["candidates"][0]["content"]["parts"][0]["text"]

# ========================= ТЕМЫ =========================

GEN_TOPICS = [
    "Строение атома",
    "Электронная конфигурация",
    "Изотоп, изобар, изотон",
    "Ядерные реакции",
    "Периодический закон",
    "Химическая связь",
    "Валентность",
    "Гибридизация и кристаллическая решётка",
    "Аллотропия",
    "Простые и сложные вещества",
    "Оксиды",
    "Основания",
    "Кислоты",
    "Соли",
    "Химические и физические явления, сублимация",
    "Скорость химической реакции",
    "Химическое равновесие",
    "Тепловые эффекты",
    "ОВР (окислительно-восстановительные реакции)",
    "Газовые законы",
    "Раствор",
    "Растворимость",
    "Электролиты и неэлектролиты",
    "Электролиз",
    "Гидролиз",
    "Водородный показатель",
    "Жёсткость воды",
    "Другие",
]

ORG_TOPICS = [
    "Алканы",
    "Алкены",
    "Алкины",
    "Алкадиены",
    "Циклоалканы",
    "Арены",
    "Спирты",
    "Фенолы",
    "Альдегиды и кетоны",
    "Карбоновые кислоты",
    "Простые и сложные эфиры",
    "Амины",
    "Аминокислоты",
    "Углеводы",
    "Жиры и масла",
    "Другие",
]

GRADES = ["7 класс", "8 класс", "9 класс", "10 класс", "11 класс", "Другие"]

SUBSECTIONS = {"l": "📖 Лекция", "v": "🎥 Видеоурок", "z": "📝 Тесты"}
BRANCH_NAMES = {"g": "Общая и неорганическая химия", "o": "Органическая химия"}
BRANCH_TOPICS = {"g": GEN_TOPICS, "o": ORG_TOPICS}

# ========================= КОНТЕНТ (с хранением в файле) =========================
# Весь материал, который добавляют кнопкой "➕ Добавить" внутри бота,
# сохраняется в content_store.json рядом с этим файлом и не теряется при перезапуске.
STORE = load_store()
TASKS_BANK_KEY = "tasks_bank"

DEFAULT_TASKS = [
    "Задача: Вычислите массу воды, образующейся при сгорании 11.2 л (н.у.) метана.\n"
    "Решение: n(CH4)=V/Vm=11.2/22.4=0.5 моль. CH4+2O2→CO2+2H2O. "
    "n(H2O)=2×0.5=1 моль. m(H2O)=1×18=18 г.",

    "Задача: Определите молярную массу вещества, если 4.4 г его занимают объём 2.24 л при н.у.\n"
    "Решение: n=V/Vm=2.24/22.4=0.1 моль. M=m/n=4.4/0.1=44 г/моль (например, CO2).",

    "Задача: Сколько граммов NaOH требуется для нейтрализации 200 мл 0.5 М раствора HCl?\n"
    "Решение: n(HCl)=C×V=0.5×0.2=0.1 моль. NaOH+HCl→NaCl+H2O, n(NaOH)=0.1 моль. "
    "m=n×M=0.1×40=4 г.",

    "Задача: Вычислите массовую долю кислорода в серной кислоте H2SO4.\n"
    "Решение: M(H2SO4)=98 г/моль. Масса O=4×16=64. w(O)=64/98×100%≈65.3%.",

    "Задача: Какой объём водорода (н.у.) выделится при растворении 13 г цинка в избытке соляной кислоты?\n"
    "Решение: n(Zn)=13/65=0.2 моль. Zn+2HCl→ZnCl2+H2. n(H2)=0.2 моль. V=0.2×22.4=4.48 л.",

    "Задача: Смешали 100 г 20%-ного раствора NaCl со 150 г воды. Найдите массовую долю соли в новом растворе.\n"
    "Решение: m(NaCl)=100×0.2=20 г. Общая масса=100+150=250 г. w=20/250×100%=8%.",

    "Задача (органика): Вещество содержит 80% углерода и 20% водорода по массе, его молярная масса — 30 г/моль. "
    "Определите молекулярную формулу.\n"
    "Решение: В 100 г вещества: n(C)=80/12≈6.67 моль; n(H)=20/1=20 моль. "
    "Отношение n(C):n(H)=1:3 → простейшая формула CH3 (M=15). "
    "Так как M(в-ва)=30=2×15, истинная формула — C2H6 (этан).",

    "Задача: Вычислите количество теплоты, выделившееся при сгорании 5 г угля (Qгор(C)=393 кДж/моль).\n"
    "Решение: n(C)=5/12≈0.417 моль. Q=0.417×393≈164 кДж.",

    "Задача: К 50 мл 2М раствора AgNO3 добавили избыток NaCl. Какая масса осадка образуется?\n"
    "Решение: n(AgNO3)=2×0.05=0.1 моль. AgNO3+NaCl→AgCl↓+NaNO3. "
    "n(AgCl)=0.1 моль. M(AgCl)=143.5 г/моль. m=14.35 г.",

    "Задача (органика): Вычислите объём кислорода (н.у.), необходимый для полного сгорания 4.6 г этанола C2H5OH.\n"
    "Решение: n(C2H5OH)=4.6/46=0.1 моль. C2H5OH+3O2→2CO2+3H2O. "
    "n(O2)=0.3 моль. V=0.3×22.4=6.72 л.",

    "Задача: Определите pH раствора, если концентрация ионов H⁺ равна 1×10⁻³ моль/л.\n"
    "Решение: pH=−lg[H⁺]=−lg(10⁻³)=3.",

    "Задача: Сплав меди и цинка массой 10 г обработали избытком соляной кислоты, выделилось 2.24 л водорода (н.у.). "
    "Найдите массовую долю цинка в сплаве.\n"
    "Решение: медь с HCl не реагирует, реагирует только Zn: Zn+2HCl→ZnCl2+H2. "
    "n(H2)=2.24/22.4=0.1 моль=n(Zn). m(Zn)=0.1×65=6.5 г. w(Zn)=6.5/10×100%=65%.",
]


def get_tasks_bank():
    return DEFAULT_TASKS + STORE.get(TASKS_BANK_KEY, [])


def add_task_to_bank(text):
    bank = STORE.get(TASKS_BANK_KEY, [])
    bank.append(text)
    STORE[TASKS_BANK_KEY] = bank
    save_store()


def render_task_card():
    bank = get_tasks_bank()
    if not bank:
        text = "📝 Сверхтрудные задачи\n\nБанк пуст. Добавьте первую задачу!"
        keyboard = [
            [InlineKeyboardButton("➕ Добавить задачу", callback_data="task:add")],
            [InlineKeyboardButton("⬅ Назад", callback_data="c:games")],
        ]
    else:
        task = random.choice(bank)
        text = f"📝 Сверхтрудная задача:\n\n{task}"
        keyboard = [
            [InlineKeyboardButton("🔀 Другая задача", callback_data="task:next")],
            [InlineKeyboardButton("➕ Добавить свою", callback_data="task:add")],
            [InlineKeyboardButton("⬅ Назад", callback_data="c:games")],
        ]
    return text, InlineKeyboardMarkup(keyboard)


def content_key(kind, *args):
    return "|".join([kind] + [str(a) for a in args])


def content_title_info(kind, *args):
    """Возвращает (заголовок, callback для 'Назад', текст для пустой темы)."""
    if kind == "t":
        branch, sub, idx = args[0], args[1], int(args[2])
        topic = BRANCH_TOPICS[branch][idx]
        return f"{SUBSECTIONS[sub]}: {topic}", f"tm:{branch}:{idx}", "Материал по этой теме ещё не добавлен."
    if kind == "tb":
        idx = int(args[0])
        grade = GRADES[idx]
        return f"📚 {grade}", "c:tb", f"Учебники и книги для «{grade}» пока не добавлены."
    if kind == "tbl":
        idx = int(args[0])
        grade = GRADES[idx]
        return f"📖 Лекции учебников — {grade}", "c:tbl", f"Лекции по учебникам для «{grade}» пока не добавлены."
    if kind == "cp":
        branch, idx = args[0], int(args[1])
        topic = BRANCH_TOPICS[branch][idx]
        return f"🔗 Цепная задача: {topic}", f"c:cpl:{branch}", "Цепочка превращений по этой теме ещё не добавлена."
    if kind == "dtm":
        return "🧪 ДТМ тесты", "c:main", "Материалы для подготовки к ДТМ по химии ещё не добавлены."
    if kind == "formulas":
        return "📐 Общие формулы", "c:main", "Дополнительные формулы ещё не добавлены."
    return "Материал", "main", "Пусто."


def get_items(key):
    """Возвращает список (id, item) для темы. Автоматически переводит старые форматы в новый."""
    val = STORE.get(key)
    if val is None:
        return []

    if isinstance(val, dict) and val.get("type") == "file":
        # старый формат: один файл без списка
        item = {"kind": "file", "file_type": val.get("file_type"), "file_id": val.get("file_id"), "caption": val.get("caption")}
        new_id = uuid.uuid4().hex[:8]
        newval = {new_id: item}
        STORE[key] = newval
        save_store()
        return list(newval.items())

    if isinstance(val, str):
        item = {"kind": "text", "value": val}
        new_id = uuid.uuid4().hex[:8]
        newval = {new_id: item}
        STORE[key] = newval
        save_store()
        return list(newval.items())

    if isinstance(val, list):
        # промежуточный формат: список без ID
        newval = {uuid.uuid4().hex[:8]: it for it in val}
        STORE[key] = newval
        save_store()
        return list(newval.items())

    if isinstance(val, dict):
        # уже в текущем формате: {id: item}
        return list(val.items())

    return []


def add_item(key, item):
    existing = dict(get_items(key))
    new_id = uuid.uuid4().hex[:8]
    existing[new_id] = item
    STORE[key] = existing
    save_store()


def delete_item(key, item_id):
    items = dict(get_items(key))
    if item_id in items:
        items.pop(item_id)
        if items:
            STORE[key] = items
        else:
            STORE.pop(key, None)
        save_store()
        return True
    return False


def item_preview(item, maxlen=35):
    if item.get("kind") == "text":
        t = item["value"].replace("\n", " ").strip()
        return (t[:maxlen] + "…") if len(t) > maxlen else t
    labels = {"photo": "🖼 Картинка", "video": "🎥 Видео"}
    base = labels.get(item.get("file_type"), "📎 Файл")
    if item.get("caption"):
        cap = item["caption"][:25]
        return f"{base}: {cap}"
    return base


def render_content_page(kind, *args):
    """Возвращает (текст, клавиатура) со списком всех материалов темы."""
    key = content_key(kind, *args)
    title, back_cb, empty_text = content_title_info(kind, *args)
    items = get_items(key)

    if not items:
        text = f"{title}\n\n{empty_text}"
        buttons = [
            [InlineKeyboardButton("➕ Добавить", callback_data=f"add:{key}")],
            [InlineKeyboardButton("⬅ Назад", callback_data=back_cb)],
        ]
    else:
        text = f"{title}\n\nМатериалов: {len(items)}. Выберите, чтобы посмотреть:"
        buttons = [
            [InlineKeyboardButton(f"{i + 1}. {item_preview(it)}", callback_data=f"view:{key}:{item_id}")]
            for i, (item_id, it) in enumerate(items)
        ]
        buttons.append([InlineKeyboardButton("➕ Добавить ещё", callback_data=f"add:{key}")])
        buttons.append([InlineKeyboardButton("⬅ Назад", callback_data=back_cb)])

    if kind == "formulas":
        text = FORMULAS_TEXT + "\n\n" + "─" * 20 + "\n\n" + text

    return text, InlineKeyboardMarkup(buttons)


def render_content_page_by_key(key):
    parts = key.split("|")
    return render_content_page(parts[0], *parts[1:])


def render_item_page(key, item_id):
    """Возвращает (текст, клавиатура, файл-или-None) для одного конкретного материала по его ID."""
    items = dict(get_items(key))
    if item_id not in items:
        text, kb = render_content_page_by_key(key)
        return "⚠ Этот материал уже удалён.\n\n" + text, kb, None
    item = items[item_id]
    if item.get("kind") == "text":
        text = item["value"]
        file_item = None
    else:
        labels = {"photo": "🖼 Прикреплено изображение", "video": "🎥 Прикреплено видео"}
        label = labels.get(item.get("file_type"), "📎 Прикреплён файл")
        text = label
        if item.get("caption"):
            text += f"\n{item['caption']}"
        text += "\n\n(файл отправлен отдельным сообщением ниже)"
        file_item = item
    buttons = [
        [InlineKeyboardButton("🗑 Удалить этот", callback_data=f"delitem:{key}:{item_id}")],
        [InlineKeyboardButton("⬅ К списку", callback_data=f"list:{key}")],
    ]
    return text, InlineKeyboardMarkup(buttons), file_item


async def send_item_file(context, chat_id, item):
    if not item or item.get("kind") != "file":
        return
    try:
        file_type = item.get("file_type")
        if file_type == "photo":
            await context.bot.send_photo(chat_id, item["file_id"])
        elif file_type == "video":
            await context.bot.send_video(chat_id, item["file_id"])
        else:
            await context.bot.send_document(chat_id, item["file_id"])
    except Exception:
        pass


# Общие формулы для решения задач (реальный контент)
FORMULAS_TEXT = (
    "📐 Общие формулы для решения задач\n\n"
    "• Количество вещества: n = m / M = V / Vm = N / Nа\n"
    "• Молярная масса: M = m / n (г/моль)\n"
    "• Молярный объём газа (н.у.): Vm = 22.4 л/моль\n"
    "• Число Авогадро: Nа = 6.022×10²³\n"
    "• Массовая доля вещества: w = m(вещества) / m(раствора) × 100%\n"
    "• Молярная концентрация: C = n / V(раствора)\n"
    "• Уравнение состояния газа: pV = nRT\n"
    "• pH раствора: pH = −lg[H⁺]\n"
    "• Тепловой эффект реакции: Q = c·m·ΔT\n"
    "• Массовая доля элемента в веществе: w = (n·Ar) / Mr × 100%\n"
    "• Закон сохранения массы: сумма масс реагентов = сумма масс продуктов"
)

# Квиз: список (вопрос, [варианты], индекс правильного)
QUIZ = [
    ("Сколько протонов в ядре атома углерода?", ["4", "6", "8", "12"], 1),
    ("Какой заряд у электрона?", ["+1", "0", "-1", "+2"], 2),
    ("Формула воды?", ["CO2", "H2O", "NaCl", "O2"], 1),
    ("Что такое моль?", ["Единица массы", "Единица количества вещества", "Единица объёма", "Единица давления"], 1),
    ("pH нейтральной среды равен:", ["0", "7", "14", "1"], 1),
    ("Какой газ выделяется при взаимодействии металла с кислотой?", ["O2", "CO2", "H2", "N2"], 2),
    ("Алканы — это углеводороды с какими связями?", ["Только одинарными", "Двойными", "Тройными", "Ароматическими"], 0),
    ("Как называется реакция A+B→AB?", ["Разложения", "Соединения", "Замещения", "Обмена"], 1),
    ("Какой элемент имеет самую высокую электроотрицательность?", ["Кислород", "Фтор", "Азот", "Хлор"], 1),
    ("Число Авогадро равно:", ["6.022×10²³", "3.14", "9.8", "22.4"], 0),
    ("Формула серной кислоты?", ["H2SO3", "H2SO4", "HSO4", "H2S"], 1),
    ("Какой тип связи в молекуле Cl2?", ["Ионная", "Ковалентная неполярная", "Металлическая", "Водородная"], 1),
    ("Сколько атомов кислорода в глюкозе C6H12O6?", ["4", "5", "6", "12"], 2),
    ("Какая валентность у кислорода в большинстве соединений?", ["I", "II", "III", "IV"], 1),
    ("Какой газ образуется при разложении пероксида водорода H2O2?", ["H2", "O2", "CO2", "N2"], 1),
    ("Сколько электронов может находиться на первом энергетическом уровне?", ["2", "4", "8", "18"], 0),
    ("Формула аммиака?", ["NH4", "NH3", "N2H4", "HN3"], 1),
    ("Какая кислота содержится в желудке человека?", ["Серная", "Соляная", "Уксусная", "Азотная"], 1),
    ("Что такое изомеры?", [
        "Вещества с одинаковой формулой, но разным строением",
        "Разновидности одного и того же атома",
        "Вещества с разной молярной массой",
        "Соединения одного элемента с кислородом",
    ], 0),
    ("Какой элемент образует наибольшее число соединений в природе?", ["Кислород", "Водород", "Углерод", "Азот"], 2),
    ("Формула метана?", ["CH4", "C2H6", "CH3OH", "C2H2"], 0),
    ("Как называется переход твёрдого вещества сразу в газ, минуя жидкость?", ["Конденсация", "Сублимация", "Кристаллизация", "Испарение"], 1),
    ("Сколько связей образует атом углерода в органических соединениях?", ["2", "3", "4", "6"], 2),
    ("Какая функциональная группа у спиртов?", ["-COOH", "-OH", "-CHO", "-NH2"], 1),
]

# Продолжение реакций: (начало реакции, продукт/ответ)
REACTIONS = [
    ("CH4 + O2 → ?", "CO2 + H2O (горение метана)"),
    ("Na + H2O → ?", "NaOH + H2 (щёлочь и водород)"),
    ("CaCO3 → (при нагревании) ?", "CaO + CO2"),
    ("HCl + NaOH → ?", "NaCl + H2O (реакция нейтрализации)"),
    ("Zn + HCl → ?", "ZnCl2 + H2"),
    ("C2H4 + H2 → ?", "C2H6 (гидрирование этилена)"),
    ("Fe + O2 → ?", "Fe3O4 / Fe2O3 (оксид железа)"),
    ("CH3COOH + C2H5OH → ?", "CH3COOC2H5 + H2O (реакция этерификации)"),
    ("N2 + H2 → ?", "NH3 (синтез аммиака)"),
    ("AgNO3 + NaCl → ?", "AgCl↓ + NaNO3"),
    ("C + O2 → ?", "CO2 (горение угля)"),
    ("CuSO4 + Fe → ?", "FeSO4 + Cu (вытеснение меди железом)"),
    ("KOH + H2SO4 → ?", "K2SO4 + H2O"),
    ("CH4 + Cl2 → (на свету) ?", "CH3Cl + HCl (хлорирование метана)"),
    ("C2H5OH + O2 → (горение) ?", "CO2 + H2O"),
    ("CaO + H2O → ?", "Ca(OH)2 (гашение извести)"),
    ("BaCl2 + Na2SO4 → ?", "BaSO4↓ + NaCl"),
    ("C6H12O6 → (брожение) ?", "C2H5OH + CO2 (спиртовое брожение)"),
    ("Al + HCl → ?", "AlCl3 + H2"),
    ("SO2 + O2 → (катализатор) ?", "SO3"),
    ("NH3 + HCl → ?", "NH4Cl"),
    ("CH2=CH2 + Br2 → ?", "CH2Br−CH2Br (бромирование этилена)"),
    ("Na2CO3 + HCl → ?", "NaCl + H2O + CO2"),
    ("Fe2O3 + CO → (доменный процесс) ?", "Fe + CO2"),
]


# ========================= КЛАВИАТУРЫ =========================

def chunk(lst, n=1):
    return [lst[i:i + n] for i in range(0, len(lst), n)]


def main_menu_kb():
    keyboard = [
        [InlineKeyboardButton("🧪 Общая и неорганическая химия", callback_data="br:g")],
        [InlineKeyboardButton("⚗ Органическая химия", callback_data="br:o")],
        [InlineKeyboardButton("📦 Общее для химии", callback_data="c:main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def topic_menu_kb(branch):
    topics = BRANCH_TOPICS[branch]
    buttons = [
        InlineKeyboardButton(t, callback_data=f"tm:{branch}:{i}")
        for i, t in enumerate(topics)
    ]
    keyboard = chunk(buttons, 1)
    keyboard.append([InlineKeyboardButton("⬅ Назад", callback_data="main")])
    return InlineKeyboardMarkup(keyboard)


def topic_type_kb(branch, idx):
    keyboard = [
        [InlineKeyboardButton(SUBSECTIONS["l"], callback_data=f"tc:{branch}:l:{idx}")],
        [InlineKeyboardButton(SUBSECTIONS["v"], callback_data=f"tc:{branch}:v:{idx}")],
        [InlineKeyboardButton(SUBSECTIONS["z"], callback_data=f"tc:{branch}:z:{idx}")],
        [InlineKeyboardButton("⬅ Назад", callback_data=f"br:{branch}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def back_kb(callback_data):
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Назад", callback_data=callback_data)]])


def cancel_kb(key):
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=f"list:{key}")]])


def confirm_delitem_kb(key, idx):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да, удалить", callback_data=f"delitemok:{key}:{idx}")],
        [InlineKeyboardButton("❌ Нет, отмена", callback_data=f"delitemcancel:{key}:{idx}")],
    ])


def common_menu_kb():
    keyboard = [
        [InlineKeyboardButton("📚 Учебники и другие книги", callback_data="c:tb")],
        [InlineKeyboardButton("📖 Лекции учебников", callback_data="c:tbl")],
        [InlineKeyboardButton("🔗 Цепные задачи", callback_data="c:cp")],
        [InlineKeyboardButton("📐 Общие формулы", callback_data="c:formulas")],
        [InlineKeyboardButton("🧪 ДТМ тесты", callback_data="c:dtm")],
        [InlineKeyboardButton("🤖 Спросить у ИИ", callback_data="c:ai")],
        [InlineKeyboardButton("🎮 Игры для развития", callback_data="c:games")],
        [InlineKeyboardButton("⬅ Назад", callback_data="main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def grades_kb():
    buttons = [InlineKeyboardButton(g, callback_data=f"c:tbg:{i}") for i, g in enumerate(GRADES)]
    keyboard = chunk(buttons, 2)
    keyboard.append([InlineKeyboardButton("⬅ Назад", callback_data="c:main")])
    return InlineKeyboardMarkup(keyboard)


def grades_lectures_kb():
    buttons = [InlineKeyboardButton(g, callback_data=f"c:tblg:{i}") for i, g in enumerate(GRADES)]
    keyboard = chunk(buttons, 2)
    keyboard.append([InlineKeyboardButton("⬅ Назад", callback_data="c:main")])
    return InlineKeyboardMarkup(keyboard)


def chain_branch_kb():
    keyboard = [
        [InlineKeyboardButton("Общая и неорганическая химия", callback_data="c:cpl:g")],
        [InlineKeyboardButton("Органическая химия", callback_data="c:cpl:o")],
        [InlineKeyboardButton("⬅ Назад", callback_data="c:main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def chain_topic_kb(branch):
    topics = BRANCH_TOPICS[branch]
    buttons = [
        InlineKeyboardButton(t, callback_data=f"cct:{branch}:{i}")
        for i, t in enumerate(topics)
    ]
    keyboard = chunk(buttons, 1)
    keyboard.append([InlineKeyboardButton("⬅ Назад", callback_data="c:cp")])
    return InlineKeyboardMarkup(keyboard)


def games_menu_kb():
    keyboard = [
        [InlineKeyboardButton("📝 Задачи (сверхтрудные)", callback_data="c:g:tasks")],
        [InlineKeyboardButton("❓ Quiz-тест", callback_data="c:g:quiz")],
        [InlineKeyboardButton("🔄 Продолжение реакции", callback_data="c:g:react")],
        [InlineKeyboardButton("⬅ Назад", callback_data="c:main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def quiz_kb(q_idx):
    question, options, _ = QUIZ[q_idx]
    keyboard = [
        [InlineKeyboardButton(opt, callback_data=f"qz:{q_idx}:{i}")]
        for i, opt in enumerate(options)
    ]
    keyboard.append([InlineKeyboardButton("⬅ Выйти из квиза", callback_data="c:games")])
    return InlineKeyboardMarkup(keyboard)


def reaction_kb(r_idx, show_answer=False):
    if not show_answer:
        keyboard = [[InlineKeyboardButton("Показать ответ", callback_data=f"rx:show:{r_idx}")]]
    else:
        nxt = random.randrange(len(REACTIONS))
        keyboard = [[InlineKeyboardButton("Следующая реакция 🔀", callback_data=f"rx:{nxt}")]]
    keyboard.append([InlineKeyboardButton("⬅ Выйти", callback_data="c:games")])
    return InlineKeyboardMarkup(keyboard)


# ========================= ХЭНДЛЕРЫ =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting_ai"] = False
    await update.message.reply_text(
        "👋 Привет! Я репетитор-бот по химии.\n"
        "Меня создал репетитор-учитель Абдусаломов Авазбек.\n"
        "По обращению: +998916634067\n\n"
        "Выберите раздел:",
        reply_markup=main_menu_kb(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n/start — главное меню\n/help — эта справка\n"
        "/add — добавить материал в тему, которую вы сейчас смотрите\n"
        "/delete — удалить материал из темы, которую вы сейчас смотрите"
    )


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Эта команда доступна только администратору бота.")
        return
    context.user_data["pending_action"] = "add"
    context.user_data.pop("last_content_key", None)
    await update.message.reply_text(
        "➕ Куда добавить материал? Выберите раздел:",
        reply_markup=main_menu_kb(),
    )


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Эта команда доступна только администратору бота.")
        return
    context.user_data["pending_action"] = "delete"
    context.user_data.pop("last_content_key", None)
    await update.message.reply_text(
        "🗑 Откуда удалить материал? Выберите раздел:",
        reply_markup=main_menu_kb(),
    )


async def show_leaf(query, context, key):
    """Показывает страницу темы; если перед этим был вызван /add или /delete —
    сразу выполняет нужное действие вместо простого показа."""
    context.user_data["last_content_key"] = key
    pending = context.user_data.pop("pending_action", None)

    if pending == "add":
        context.user_data["awaiting_content"] = key
        await query.edit_message_text(
            "✏ Отправьте материал следующим сообщением: текст, ссылку, PDF, DOCX, картинку или видео.",
            reply_markup=cancel_kb(key),
        )
        return

    if pending == "delete":
        items = get_items(key)
        if not items:
            text, kb = render_content_page_by_key(key)
            await query.edit_message_text("В этой теме материала ещё нет — нечего удалять.\n\n" + text, reply_markup=kb)
            return
        text, kb = render_content_page_by_key(key)
        await query.edit_message_text("🗑 Выберите материал, который нужно удалить:\n\n" + text, reply_markup=kb)
        return

    text, kb = render_content_page_by_key(key)
    await query.edit_message_text(text, reply_markup=kb)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    parts = data.split(":")

    # ---- главное меню ----
    if data == "main":
        context.user_data["awaiting_ai"] = False
        await query.edit_message_text("Выберите раздел:", reply_markup=main_menu_kb())
        return

    # ---- ветка (общая/органическая): сразу список тем ----
    if parts[0] == "br":
        branch = parts[1]
        await query.edit_message_text(
            f"{BRANCH_NAMES[branch]}\n\nВыберите тему:",
            reply_markup=topic_menu_kb(branch),
        )
        return

    # ---- выбор типа материала внутри темы (лекция/видеоурок/тесты) ----
    if parts[0] == "tm":
        branch, idx = parts[1], int(parts[2])
        topic = BRANCH_TOPICS[branch][idx]
        await query.edit_message_text(
            f"{BRANCH_NAMES[branch]} — {topic}\n\nВыберите:",
            reply_markup=topic_type_kb(branch, idx),
        )
        return

    # ---- содержимое темы (лекция/видео/задачи) ----
    if parts[0] == "tc":
        branch, sub, idx = parts[1], parts[2], parts[3]
        await show_leaf(query, context, content_key("t", branch, sub, idx))
        return

    # ---- добавить / изменить материал ----
    if data.startswith("add:"):
        if not is_admin(query.from_user.id):
            await query.answer("⛔ Только администратор может добавлять материалы.", show_alert=True)
            return
        key = data[4:]
        context.user_data["awaiting_content"] = key
        context.user_data["last_content_key"] = key
        await query.edit_message_text(
            "✏ Отправьте материал следующим сообщением: текст, ссылку, PDF, DOCX, картинку или видео.",
            reply_markup=cancel_kb(key),
        )
        return

    # ---- вернуться к списку материалов темы ----
    if data.startswith("list:"):
        key = data[5:]
        context.user_data.pop("awaiting_content", None)
        text, kb = render_content_page_by_key(key)
        await query.edit_message_text(text, reply_markup=kb)
        return

    # ---- посмотреть конкретный материал из списка ----
    if data.startswith("view:"):
        key, item_id = data[5:].rsplit(":", 1)
        text, kb, file_item = render_item_page(key, item_id)
        await query.edit_message_text(text, reply_markup=kb)
        await send_item_file(context, query.message.chat_id, file_item)
        return

    # ---- удалить конкретный материал (с подтверждением) ----
    if data.startswith("delitem:"):
        if not is_admin(query.from_user.id):
            await query.answer("⛔ Только администратор может удалять материалы.", show_alert=True)
            return
        key, item_id = data[8:].rsplit(":", 1)
        await query.edit_message_text(
            "🗑 Удалить этот материал? Это нельзя отменить.",
            reply_markup=confirm_delitem_kb(key, item_id),
        )
        return

    if data.startswith("delitemok:"):
        if not is_admin(query.from_user.id):
            await query.answer("⛔ Доступ запрещён.", show_alert=True)
            return
        key, item_id = data[10:].rsplit(":", 1)
        delete_item(key, item_id)
        text, kb = render_content_page_by_key(key)
        await query.edit_message_text("🗑 Удалено.\n\n" + text, reply_markup=kb)
        return

    if data.startswith("delitemcancel:"):
        key, item_id = data[14:].rsplit(":", 1)
        text, kb, file_item = render_item_page(key, item_id)
        await query.edit_message_text(text, reply_markup=kb)
        await send_item_file(context, query.message.chat_id, file_item)
        return

    # ---- раздел "Общее для химии" ----
    if data == "c:main":
        await query.edit_message_text("📦 Общее для химии\n\nВыберите раздел:", reply_markup=common_menu_kb())
        return

    if data == "c:tb":
        await query.edit_message_text("📚 Учебники и другие книги\n\nВыберите класс:", reply_markup=grades_kb())
        return

    if parts[0] == "c" and parts[1] == "tbg":
        idx = parts[2]
        await show_leaf(query, context, content_key("tb", idx))
        return

    if data == "c:tbl":
        await query.edit_message_text("📖 Лекции учебников\n\nВыберите класс:", reply_markup=grades_lectures_kb())
        return

    if parts[0] == "c" and parts[1] == "tblg":
        idx = parts[2]
        await show_leaf(query, context, content_key("tbl", idx))
        return

    if data == "c:cp":
        await query.edit_message_text("🔗 Цепные задачи\n\nВыберите раздел химии:", reply_markup=chain_branch_kb())
        return

    if parts[0] == "c" and parts[1] == "cpl":
        branch = parts[2]
        await query.edit_message_text(
            f"Цепные задачи — {BRANCH_NAMES[branch]}\n\nВыберите тему:",
            reply_markup=chain_topic_kb(branch),
        )
        return

    if parts[0] == "cct":
        branch, idx = parts[1], parts[2]
        await show_leaf(query, context, content_key("cp", branch, idx))
        return

    if data == "c:formulas":
        await show_leaf(query, context, content_key("formulas"))
        return

    if data == "c:dtm":
        await show_leaf(query, context, content_key("dtm"))
        return

    if data == "c:ai":
        context.user_data["awaiting_ai"] = True
        await query.edit_message_text(
            "🤖 Спросите меня о чём угодно по химии — просто напишите вопрос сообщением.",
            reply_markup=back_kb("c:main"),
        )
        return

    if data == "c:games":
        context.user_data["awaiting_ai"] = False
        await query.edit_message_text("🎮 Игры для развития\n\nВыберите игру:", reply_markup=games_menu_kb())
        return

    if data == "c:g:tasks":
        pending = context.user_data.pop("pending_action", None)
        if pending == "add":
            context.user_data["awaiting_content"] = "TASKS_BANK_APPEND"
            await query.edit_message_text(
                "✏ Отправьте текст задачи (условие и решение) следующим сообщением.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("❌ Отмена", callback_data="c:g:tasks")]]
                ),
            )
            return
        if pending == "delete":
            await query.edit_message_text(
                "В этом разделе накопительный банк задач — удаление одной задачи пока не поддерживается.",
                reply_markup=back_kb("c:games"),
            )
            return
        text, kb = render_task_card()
        await query.edit_message_text(text, reply_markup=kb)
        return

    if data == "task:next":
        text, kb = render_task_card()
        await query.edit_message_text(text, reply_markup=kb)
        return

    if data == "task:add":
        if not is_admin(query.from_user.id):
            await query.answer("⛔ Только администратор может добавлять задачи.", show_alert=True)
            return
        context.user_data["awaiting_content"] = "TASKS_BANK_APPEND"
        await query.edit_message_text(
            "✏ Отправьте текст задачи (условие и решение) следующим сообщением.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("❌ Отмена", callback_data="c:g:tasks")]]
            ),
        )
        return

    if data == "c:g:quiz":
        context.user_data["quiz_score"] = 0
        context.user_data["quiz_count"] = 0
        q_idx = random.randrange(len(QUIZ))
        await query.edit_message_text(
            f"❓ Вопрос:\n\n{QUIZ[q_idx][0]}", reply_markup=quiz_kb(q_idx)
        )
        return

    if parts[0] == "qz":
        q_idx, chosen = int(parts[1]), int(parts[2])
        question, options, correct = QUIZ[q_idx]
        score = context.user_data.get("quiz_score", 0)
        count = context.user_data.get("quiz_count", 0) + 1
        if chosen == correct:
            score += 1
            result = "✅ Верно!"
        else:
            result = f"❌ Неверно. Правильный ответ: {options[correct]}"
        context.user_data["quiz_score"] = score
        context.user_data["quiz_count"] = count

        next_idx = random.randrange(len(QUIZ))
        text = f"{result}\n\n📊 Счёт: {score}/{count}\n\n❓ Следующий вопрос:\n\n{QUIZ[next_idx][0]}"
        await query.edit_message_text(text, reply_markup=quiz_kb(next_idx))
        return

    if data == "c:g:react":
        idx = random.randrange(len(REACTIONS))
        start_text, _ = REACTIONS[idx]
        await query.edit_message_text(f"🔄 Реакция:\n\n{start_text}", reply_markup=reaction_kb(idx))
        return

    if parts[0] == "rx":
        if parts[1] == "show":
            idx = int(parts[2])
            start_text, product = REACTIONS[idx]
            text = f"🔄 Реакция {idx + 1}/{len(REACTIONS)}:\n\n{start_text}\n\nОтвет: {product}"
            await query.edit_message_text(text, reply_markup=reaction_kb(idx, show_answer=True))
        else:
            idx = int(parts[1])
            start_text, _ = REACTIONS[idx]
            text = f"🔄 Реакция {idx + 1}/{len(REACTIONS)}:\n\n{start_text}"
            await query.edit_message_text(text, reply_markup=reaction_kb(idx))
        return


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает свободный текст: сохранение материала, вопрос к ИИ, или команды add/delete словом."""
    msg = update.message.text.strip().lower()

    # ---- если ждём текст материала — сохраняем его, даже если он похож на "add"/"delete" ----
    if context.user_data.get("awaiting_content"):
        key = context.user_data.pop("awaiting_content")
        if key == "TASKS_BANK_APPEND":
            add_task_to_bank(update.message.text)
            text, kb = render_task_card()
            await update.message.reply_text("✅ Задача добавлена в банк!\n\n" + text, reply_markup=kb)
            return
        add_item(key, {"kind": "text", "value": update.message.text})
        text, kb = render_content_page_by_key(key)
        await update.message.reply_text("✅ Материал добавлен!\n\n" + text, reply_markup=kb)
        return

    # ---- слова add/добавить и delete/удалить работают как команды /add и /delete ----
    if msg in ("add", "добавить", "добавь"):
        await add_command(update, context)
        return

    if msg in ("delete", "удалить", "удали"):
        await delete_command(update, context)
        return

    if context.user_data.get("awaiting_ai"):
        question = update.message.text
        await update.message.reply_text("🤖 Думаю...")
        try:
            answer = await asyncio.to_thread(call_gemini, question)
            await update.message.reply_text(answer)
        except Exception as e:
            await update.message.reply_text(
                "⚠ Не удалось получить ответ от ИИ. Проверьте, что указан правильный "
                "GEMINI_API_KEY и есть интернет.\n\n"
                f"Ошибка: {e}"
            )
    else:
        await update.message.reply_text("Напишите /start, чтобы открыть меню.")


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет присланный документ (PDF, DOCX и т.д.) как материал темы."""
    if not context.user_data.get("awaiting_content"):
        return
    key = context.user_data.pop("awaiting_content")
    if key == "TASKS_BANK_APPEND":
        await update.message.reply_text(
            "В разделе «Сверхтрудные задачи» пока принимается только текст (условие и решение)."
        )
        return
    doc = update.message.document
    add_item(key, {
        "kind": "file",
        "file_type": "document",
        "file_id": doc.file_id,
        "caption": update.message.caption or doc.file_name,
    })
    text, kb = render_content_page_by_key(key)
    await update.message.reply_text("✅ Файл добавлен!\n\n" + text, reply_markup=kb)


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет присланную картинку как материал темы."""
    if not context.user_data.get("awaiting_content"):
        return
    key = context.user_data.pop("awaiting_content")
    if key == "TASKS_BANK_APPEND":
        await update.message.reply_text(
            "В разделе «Сверхтрудные задачи» пока принимается только текст (условие и решение)."
        )
        return
    photo = update.message.photo[-1]
    add_item(key, {
        "kind": "file",
        "file_type": "photo",
        "file_id": photo.file_id,
        "caption": update.message.caption or "",
    })
    text, kb = render_content_page_by_key(key)
    await update.message.reply_text("✅ Картинка добавлена!\n\n" + text, reply_markup=kb)


async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет присланное видео как материал темы."""
    if not context.user_data.get("awaiting_content"):
        return
    key = context.user_data.pop("awaiting_content")
    if key == "TASKS_BANK_APPEND":
        await update.message.reply_text(
            "В разделе «Сверхтрудные задачи» пока принимается только текст (условие и решение)."
        )
        return
    video = update.message.video
    add_item(key, {
        "kind": "file",
        "file_type": "video",
        "file_id": video.file_id,
        "caption": update.message.caption or "",
    })
    text, kb = render_content_page_by_key(key)
    await update.message.reply_text("✅ Видео добавлено!\n\n" + text, reply_markup=kb)


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # не засоряем логи


def _run_health_server():
    """Крошечный веб-сервер, нужен только чтобы Render считал сервис 'Web Service'
    и не усыплял его. Реальную работу делает Telegram-бот ниже."""
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    server.serve_forever()


def main():
    if TOKEN == "ВАШ_ТОКЕН_ОТ_BOTFATHER":
        print("⚠ Сначала вставьте свой токен в переменную TOKEN!")
        return

    if _USE_CLOUD_STORE:
        print(f"☁ Облачное хранилище включено. Bin ID: {JSONBIN_BIN_ID}")
    else:
        print("💾 Облачное хранилище НЕ настроено — используется локальный файл (данные пропадут при передеплое!)")

    threading.Thread(target=_run_health_server, daemon=True).start()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.VIDEO, video_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("Бот запущен! Нажмите Ctrl+C, чтобы остановить.")
    app.run_polling()


if __name__ == "__main__":
    main()
