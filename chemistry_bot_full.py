# -*- coding: utf-8 -*-
"""
Обучающий Telegram-бот по химии — полная версия с разделами.

КАК ЗАПУСТИТЬ:
1. pip install python-telegram-bot
   (для "Спросить у ИИ" используется прямой запрос к серверу Gemini)
2. Вставьте токен бота (от @BotFather) в TOKEN ниже.
3. Для "Спросить у ИИ" вставьте ключ Gemini в GEMINI_API_KEY
   (получить бесплатно: aistudio.google.com/apikey). Если ключа нет —
   просто не трогайте, остальной бот будет работать без этого раздела.
4. Запустите: python chemistry_bot_full.py
"""

import asyncio
import json
import os
import random
import threading
import urllib.request
import urllib.error
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
# окружения BOT_TOKEN / GEMINI_KEY. Если их нет — используются значения ниже.
TOKEN = os.environ.get("BOT_TOKEN", "ВАШ_ТОКЕН_ОТ_BOTFATHER").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_KEY", "ВАШ_КЛЮЧ_GEMINI").strip()  # aistudio.google.com/apikey

# Только этот Telegram ID может добавлять/удалять материалы.
try:
    ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0


def is_admin(user_id):
    return ADMIN_ID != 0 and user_id == ADMIN_ID

STORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "content_store.json")

# Облачное хранение (jsonbin.io) — чтобы материалы не терялись при передеплое на Render.
JSONBIN_API_KEY = os.environ.get("JSONBIN_API_KEY", "").strip()
JSONBIN_BIN_ID = os.environ.get("JSONBIN_BIN_ID", "").strip()
_USE_CLOUD_STORE = bool(JSONBIN_API_KEY and JSONBIN_BIN_ID)


def load_store():
    if _USE_CLOUD_STORE:
        try:
            url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest"
            req = urllib.request.Request(
                url,
                headers={
                    "X-Master-Key": JSONBIN_API_KEY,
                    "User-Agent": "Mozilla/5.0 (compatible; ChemistryBot/1.0)",
                },
            )
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
                headers={
                    "X-Master-Key": JSONBIN_API_KEY,
                    "Content-Type": "application/json",
                    "X-Bin-Versioning": "false",
                    "User-Agent": "Mozilla/5.0 (compatible; ChemistryBot/1.0)",
                },
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
    """Прямой запрос к Gemini API с использованием актуальной модели gemini-2.5-flash."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    )
    prompt = f"Ты — помощник по химии. Ответь кратко, понятно, по делу и структурированно: {question}"
    payload = json.dumps({
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": 1000
        }
    }).encode("utf-8")
    
    req = urllib.request.Request(
        url, 
        data=payload, 
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except urllib.error.HTTPError as e:
        error_details = e.read().decode("utf-8")
        raise RuntimeError(f"Ошибка API Google ({e.code}): {error_details}")
    except Exception as e:
        raise RuntimeError(f"Ошибка соединения или парсинга: {e}")

# ========================= ТЕМЫ =========================

GEN_TOPICS = [
    "Строение атома", "Электронная конфигурация", "Изотоп, изобар, изотон",
    "Ядерные реакции", "Периодический закон", "Химическая связь", "Валентность",
    "Гибридизация и кристаллическая решётка", "Аллотропия", "Простые и сложные вещества",
    "Оксиды", "Основания", "Кислоты", "Соли", "Химические и физические явления, сублимация",
    "Скорость химической реакции", "Химическое равновесие", "Тепловые эффекты",
    "ОВР (окислительно-восстановительные реакции)", "Газовые законы", "Раствор",
    "Растворимость", "Электролиты и неэлектролиты", "Электролиз", "Гидролиз",
    "Водородный показатель", "Жёсткость воды", "Другие"
]

ORG_TOPICS = [
    "Алканы", "Алкены", "Алкины", "Алкадиены", "Циклоалканы", "Арены",
    "Спирты", "Фенолы", "Альдегиды и кетоны", "Карбоновые кислоты",
    "Простые и сложные эфиры", "Амины", "Аминокислоты", "Углеводы",
    "Жиры и масла", "Другие"
]

GRADES = ["7 класс", "8 класс", "9 класс", "10 класс", "11 класс", "Другие"]

SUBSECTIONS = {"l": "📖 Лекция", "v": "🎥 Видеоурок", "z": "📝 Тесты"}
BRANCH_NAMES = {"g": "Общая и неорганическая химия", "o": "Органическая химия"}
BRANCH_TOPICS = {"g": GEN_TOPICS, "o": ORG_TOPICS}

# ========================= КОНТЕНТ =========================
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
    "n(H2)=2.24/22.4=0.1 моль=n(Zn). m(Zn)=0.1×65=6.5 г. w(Zn)=6.5/10×100%=65%."
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
        return f"🔗 Цепная задача: {topic}", f"tm:{branch}:{idx}", "Цепочка превращений по этой теме ещё не добавлена."
    if kind == "dtm":
        return "🧪 ДТМ тесты", "c:main", "Материалы для подготовки к ДТМ по химии ещё не добавлены."
    if kind == "formulas":
        return "📐 Общие формулы", "c:main", "Дополнительные формулы ещё не добавлены."
    return "Материал", "main", "Пусто."


def get_items(key):
    val = STORE.get(key)
    if val is None:
        return []

    if isinstance(val, dict) and val.get("type") == "file":
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
        newval = {uuid.uuid4().hex[:8]: it for it in val}
        STORE[key] = newval
        save_store()
        return list(newval.items())

    if isinstance(val, dict):
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


def render_content_page(kind, user_id, *args):
    key = content_key(kind, *args)
    title, back_cb, empty_text = content_title_info(kind, *args)
    items = get_items(key)

    buttons = []
    if not items:
        text = f"{title}\n\n{empty_text}"
        if is_admin(user_id):
            buttons.append([InlineKeyboardButton("➕ Добавить", callback_data=f"add:{key}")])
        buttons.append([InlineKeyboardButton("⬅ Назад", callback_data=back_cb)])
    else:
        text = f"{title}\n\nМатериалов: {len(items)}. Выберите, чтобы посмотреть:"
        buttons = [
            [InlineKeyboardButton(f"{i + 1}. {item_preview(it)}", callback_data=f"view:{key}:{item_id}")]
            for i, (item_id, it) in enumerate(items)
        ]
        if is_admin(user_id):
            buttons.append([InlineKeyboardButton("➕ Добавить ещё", callback_data=f"add:{key}")])
        buttons.append([InlineKeyboardButton("⬅ Назад", callback_data=back_cb)])

    if kind == "formulas":
        text = FORMULAS_TEXT + "\n\n" + "─" * 20 + "\n\n" + text

    return text, InlineKeyboardMarkup(buttons)


def render_content_page_by_key(key, user_id):
    parts = key.split("|")
    return render_content_page(parts[0], user_id, *parts[1:])


def render_item_page(key, item_id, user_id):
    items = dict(get_items(key))
    if item_id not in items:
        text, kb = render_content_page_by_key(key, user_id)
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
        
    buttons = []
    if is_admin(user_id):
        buttons.append([InlineKeyboardButton("🗑 Удалить этот", callback_data=f"delitem:{key}:{item_id}")])
    buttons.append([InlineKeyboardButton("⬅ К списку", callback_data=f"list:{key}")])
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


FORMULAS_TEXT = (
    "📐 Общие формулы для решения задач\n\n"
    "• Количество вещества: $n = m / M = V / V_m = N / N_A$\n"
    "• Молярная масса: $M = m / n$ (г/моль)\n"
    "• Молярный объём газа (н.у.): $V_m = 22.4$ л/моль\n"
    "• Число Авогадро: $N_A = 6.022 \\times 10^{23}$\n"
    "• Массовая доля вещества: $w = m(\\text{вещества}) / m(\\text{раствора}) \\times 100\\%$\n"
    "• Молярная концентрация: $C = n / V(\\text{раствора})$\n"
    "• Уравнение состояния газа: $pV = nRT$\n"
    "• pH раствора: $pH = -\\lg[H^+]$\n"
    "• Тепловой эффект реакции: $Q = c \\cdot m \\cdot \\Delta T$\n"
    "• Массовая доля элемента в веществе: $w = (n \\cdot A_r) / Mr \\times 100\\%$\n"
    "• Закон сохранения массы: сумма масс реагентов = сумма масс продуктов"
)

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


# ========================= ОБРАБОТЧИКИ ТЕЛЕГРАМ =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start."""
    user = update.effective_user
    welcome_text = (
        f"👋 Привет, {user.first_name}!\n\n"
        "Добро пожаловать в обучающий бот по химии. "
        "Здесь ты сможешь эффективно подготовиться к экзаменам, "
        "пройти интерактивные тесты и даже задать свой вопрос искусственному интеллекту!\n\n"
        "Выбери интересующий тебя раздел меню ниже 👇"
    )
    keyboard = [
        [InlineKeyboardButton("📚 Теория по разделам", callback_data="c:sections")],
        [InlineKeyboardButton("📖 Учебники по классам", callback_data="c:tb")],
        [InlineKeyboardButton("📝 ДТМ Тесты", callback_data="list:dtm")],
        [InlineKeyboardButton("🎯 Интерактив и игры", callback_data="c:games")],
        [InlineKeyboardButton("🤖 Спросить у ИИ", callback_data="c:ai")],
        [InlineKeyboardButton("📐 Формулы задач", callback_data="list:formulas")]
    ]
    
    if is_admin(user.id):
        welcome_text += "\n\n👑 *Вы авторизованы как администратор!* Вы можете добавлять и удалять контент прямо через интерфейс бота."
        
    await update.message.reply_text(
        welcome_text, 
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def menu_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Навигация по разделам меню через CallbackQuery."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "c:main":
        keyboard = [
            [InlineKeyboardButton("📚 Теория по разделам", callback_data="c:sections")],
            [InlineKeyboardButton("📖 Учебники по классам", callback_data="c:tb")],
            [InlineKeyboardButton("📝 ДТМ Тесты", callback_data="list:dtm")],
            [InlineKeyboardButton("🎯 Интерактив и игры", callback_data="c:games")],
            [InlineKeyboardButton("🤖 Спросить у ИИ", callback_data="c:ai")],
            [InlineKeyboardButton("📐 Формулы задач", callback_data="list:formulas")]
        ]
        await query.edit_message_text(
            "📍 Главное меню. Выбери интересующий тебя раздел:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data == "c:sections":
        keyboard = [
            [InlineKeyboardButton("🧪 Общая и неорганическая химия", callback_data="c:branch:g")],
            [InlineKeyboardButton("🧪 Органическая химия", callback_data="c:branch:o")],
            [InlineKeyboardButton("⬅ В главное меню", callback_data="c:main")]
        ]
        await query.edit_message_text("Выбери раздел химии:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("c:branch:"):
        branch = data.split(":")[2]
        topics = BRANCH_TOPICS[branch]
        keyboard = []
        for idx, t in enumerate(topics):
            keyboard.append([InlineKeyboardButton(f"{idx+1}. {t}", callback_data=f"tm:{branch}:{idx}")])
        keyboard.append([InlineKeyboardButton("⬅ Назад", callback_data="c:sections")])
        await query.edit_message_text(
            f"Выбери тему раздела *{BRANCH_NAMES[branch]}:*", 
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif data.startswith("tm:"):
        _, branch, idx = data.split(":")
        topic_name = BRANCH_TOPICS[branch][int(idx)]
        keyboard = [
            [InlineKeyboardButton("📖 Лекция", callback_data=f"list:{content_key('t', branch, 'l', idx)}"),
             InlineKeyboardButton("🎥 Видеоурок", callback_data=f"list:{content_key('t', branch, 'v', idx)}")],
            [InlineKeyboardButton("📝 Тесты по теме", callback_data=f"list:{content_key('t', branch, 'z', idx)}")],
            [InlineKeyboardButton("🔗 Цепная задача", callback_data=f"list:{content_key('cp', branch, idx)}")],
            [InlineKeyboardButton("⬅ К темам", callback_data=f"c:branch:{branch}")]
        ]
        await query.edit_message_text(
            f"📍 *Тема:* {topic_name}\nВыбери подраздел для изучения:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif data == "c:tb":
        keyboard = []
        for idx, grade in enumerate(GRADES):
            keyboard.append([InlineKeyboardButton(grade, callback_data=f"list:{content_key('tb', idx)}")])
        keyboard.append([InlineKeyboardButton("⬅ В главное меню", callback_data="c:main")])
        await query.edit_message_text("📚 Выберите класс для просмотра учебников:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "c:games":
        keyboard = [
            [InlineKeyboardButton("❓ Экспресс-викторина", callback_data="game:quiz")],
            [InlineKeyboardButton("⚖ Закончи реакцию", callback_data="game:reaction")],
            [InlineKeyboardButton("📝 Сверхтрудные задачи", callback_data="task:next")],
            [InlineKeyboardButton("⬅ Главное меню", callback_data="c:main")]
        ]
        await query.edit_message_text("🎮 Интерактивные игры и развлечения по химии:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "c:ai":
        if not GEMINI_API_KEY or "ВАШ_КЛЮЧ" in GEMINI_API_KEY:
            await query.edit_message_text(
                "🤖 *Раздел ИИ отключен.*\n\n"
                "Администратор бота не настроил API-ключ Gemini.\n"
                "Вы можете продолжать пользоваться остальными функциями бота!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ В главное меню", callback_data="c:main")]]),
                parse_mode="Markdown"
            )
        else:
            context.user_data["waiting_ai"] = True
            await query.edit_message_text(
                "🤖 *Задайте вопрос ИИ!*\n\n"
                "Просто напишите ваш вопрос по химии в ответном сообщении. "
                "Я обработаю ваш запрос с помощью модели **Gemini 2.5 Flash**.\n\n"
                "ℹ️ _Например: 'Какова формула фенола?' или 'Реши уравнение реакции NaOH + H2SO4'_",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Назад", callback_data="c:main")]]),
                parse_mode="Markdown"
            )

    elif data == "game:quiz":
        q_idx = random.randint(0, len(QUIZ) - 1)
        question, options, correct = QUIZ[q_idx]
        context.user_data["quiz_correct"] = correct
        keyboard = []
        for i, opt in enumerate(options):
            keyboard.append([InlineKeyboardButton(opt, callback_data=f"quiz_ans:{i}")])
        keyboard.append([InlineKeyboardButton("⬅ К играм", callback_data="c:games")])
        await query.edit_message_text(f"❓ *Вопрос:* {question}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("quiz_ans:"):
        ans_idx = int(data.split(":")[1])
        correct = context.user_data.get("quiz_correct", -1)
        if ans_idx == correct:
            msg = "🎉 *Правильно! Отличный результат!*"
        else:
            msg = "❌ *Неверно! Попробуй ещё раз.*"
        keyboard = [
            [InlineKeyboardButton("🔄 Ещё вопрос", callback_data="game:quiz")],
            [InlineKeyboardButton("⬅ К играм", callback_data="c:games")]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "game:reaction":
        r_idx = random.randint(0, len(REACTIONS) - 1)
        req_text, ans_text = REACTIONS[r_idx]
        context.user_data["reaction_answer"] = ans_text
        keyboard = [
            [InlineKeyboardButton("👁 Показать ответ", callback_data="game:reaction_ans")],
            [InlineKeyboardButton("⬅ К играм", callback_data="c:games")]
        ]
        await query.edit_message_text(f"⚖ *Завершите химическую реакцию:*\n\n`{req_text}`", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "game:reaction_ans":
        ans = context.user_data.get("reaction_answer", "Ошибочка")
        keyboard = [
            [InlineKeyboardButton("🔄 Следующая реакция", callback_data="game:reaction")],
            [InlineKeyboardButton("⬅ К играм", callback_data="c:games")]
        ]
        await query.edit_message_text(f"⚖ *Правильный ответ:*\n\n`{ans}`", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "task:next":
        text, kb = render_task_card()
        await query.edit_message_text(text, reply_markup=kb)

    elif data == "task:add":
        if not is_admin(user_id):
            await query.answer("🛑 Только администратор может добавлять задачи!", show_alert=True)
            return
        context.user_data["waiting_add_task"] = True
        await query.edit_message_text(
            "📝 Отправьте текст новой задачи в формате:\n"
            "`Задача: Текст... Решение: Подробный разбор...`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Отмена", callback_data="c:games")]]),
            parse_mode="Markdown"
        )

    elif data.startswith("list:"):
        key = data.split(":", 1)[1]
        text, kb = render_content_page_by_key(key, user_id)
        await query.edit_message_text(text, reply_markup=kb)

    elif data.startswith("view:"):
        _, key, item_id = data.split(":", 2)
        text, kb, file_item = render_item_page(key, item_id, user_id)
        await query.edit_message_text(text, reply_markup=kb)
        if file_item:
            await send_item_file(context, query.message.chat_id, file_item)

    elif data.startswith("add:"):
        key = data.split(":", 1)[1]
        if not is_admin(user_id):
            await query.answer("🛑 У вас нет прав администратора для добавления контента!", show_alert=True)
            return
        context.user_data["waiting_add_content"] = key
        await query.edit_message_text(
            f"✏ *Режим добавления материала.*\n\n"
            f"Отправьте боту текст, фотографию, видео или документ. "
            f"Я сохраню его в базу данных.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Отмена", callback_data=f"list:{key}")]])
        )

    elif data.startswith("delitem:"):
        _, key, item_id = data.split(":", 2)
        if not is_admin(user_id):
            await query.answer("🛑 У вас нет прав администратора!", show_alert=True)
            return
        if delete_item(key, item_id):
            await query.answer("✅ Материал успешно удалён!")
        else:
            await query.answer("⚠ Ошибка при удалении!")
        text, kb = render_content_page_by_key(key, user_id)
        await query.edit_message_text(text, reply_markup=kb)


async def handle_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка текстовых сообщений и медиа от пользователя."""
    user_id = update.effective_user.id
    text = update.message.text

    if text == "/start":
        context.user_data.clear()
        await start(update, context)
        return

    # 1. Если ждём вопрос для ИИ (Gemini)
    if context.user_data.get("waiting_ai"):
        if not text:
            await update.message.reply_text("Пожалуйста, отправьте текстовый вопрос для ИИ.")
            return
        
        status_msg = await update.message.reply_text("Думаю... 🤖")
        try:
            ai_response = call_gemini(text)
            await status_msg.delete()
            await update.message.reply_text(
                ai_response,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🤖 Спросить ещё раз", callback_data="c:ai"),
                                                    InlineKeyboardButton("⬅ В меню", callback_data="c:main")]])
            )
            context.user_data["waiting_ai"] = False
        except Exception as e:
            await status_msg.edit_text(
                f"⚠️ Не удалось получить ответ от ИИ.\n\nОшибка:\n`{e}`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Попробовать снова", callback_data="c:ai"),
                                                    InlineKeyboardButton("⬅ В меню", callback_data="c:main")]]),
                parse_mode="Markdown"
            )
        return

    # 2. Если админ добавляет задачу в банк сверхтрудных задач
    if context.user_data.get("waiting_add_task"):
        if not is_admin(user_id):
            context.user_data["waiting_add_task"] = False
            return
        if not text:
            await update.message.reply_text("Пожалуйста, отправьте задачу текстом.")
            return
        add_task_to_bank(text)
        context.user_data["waiting_add_task"] = False
        text, kb = render_task_card()
        await update.message.reply_text("✅ Задача успешно сохранена в банк!", reply_markup=kb)
        return

    # 3. Если админ добавляет новый контент в определенный раздел/тему
    waiting_key = context.user_data.get("waiting_add_content")
    if waiting_key:
        if not is_admin(user_id):
            context.user_data["waiting_add_content"] = None
            return

        item = None
        if update.message.text:
            item = {"kind": "text", "value": update.message.text}
        elif update.message.photo:
            photo = update.message.photo[-1]
            item = {"kind": "file", "file_type": "photo", "file_id": photo.file_id, "caption": update.message.caption or ""}
        elif update.message.video:
            video = update.message.video
            item = {"kind": "file", "file_type": "video", "file_id": video.file_id, "caption": update.message.caption or ""}
        elif update.message.document:
            doc = update.message.document
            item = {"kind": "file", "file_type": "document", "file_id": doc.file_id, "caption": update.message.caption or ""}

        if item:
            add_item(waiting_key, item)
            context.user_data["waiting_add_content"] = None
            text, kb = render_content_page_by_key(waiting_key, user_id)
            await update.message.reply_text("✅ Материал успешно добавлен!", reply_markup=kb)
        else:
            await update.message.reply_text("⚠ Неподдерживаемый тип файла. Отправьте текст, фото, видео или документ.")
        return

    await update.message.reply_text(
        "Используйте кнопки меню или команду /start для полноценного взаимодействия с ботом! 😊"
    )


# ========================= ВЕБ-СЕРВЕР ДЛЯ ХОСТИНГА =========================

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Бот работает исправно!".encode("utf-8"))

def run_web_server():
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"📡 Веб-сервер запущен на порту {port} для пинга хостинга")
    server.serve_forever()


# ========================= ТОЧКА ВХОДА =========================

def main() -> None:
    if os.environ.get("PORT"):
        threading.Thread(target=run_web_server, daemon=True).start()

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(menu_navigation))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_user_input))

    print("🚀 Обучающий бот по химии запущен на Gemini 2.5 Flash!")
    application.run_polling()


if __name__ == "__main__":
    main()

    
