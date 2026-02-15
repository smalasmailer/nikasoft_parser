import logging
import html
import re
import sys
import index
from io import StringIO
from datetime import datetime, timedelta
from typing import Any, Dict, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

"""
PARAMS
ПАРАМЕТРЫ
"""

TOKEN = "..."
JS_URL = "..."
JS_FILE = "nika_data.js"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

def download_js():
    log.info("Downloading JS...")
    text = index.load_source(url=JS_URL)
    with open(JS_FILE, "w", encoding="utf-8") as f:
        f.write(text)
    log.info("JS downloaded")

def class_natural_key(s: str):
    s = s.strip()
    m = re.search(r'\d+', s)
    if m:
        num = int(m.group())
        rest = s[m.end():].strip().lower()
        return (0, num, rest)
    else:
        return (1, s.lower(), "")

def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def load_data():
    txt = index.load_source(file_path=JS_FILE)
    return index.extract_nika_json(txt)

def render_schedule_html(data: Dict[str, Any], class_name: str, date_str: str) -> str:

    CLASSES = data.get("CLASSES", {})
    SUBJECTS = data.get("SUBJECTS", {})
    TEACHERS = data.get("TEACHERS", {})
    ROOMS = data.get("ROOMS", {})
    PERIODS = data.get("PERIODS", {})
    CLASS_SCHEDULE = data.get("CLASS_SCHEDULE", {})
    CLASS_EXCHANGE = data.get("CLASS_EXCHANGE", {})
    LESSON_TIMES = data.get("LESSON_TIMES", {})
    LESSONSINDAY = data.get("LESSONSINDAY", 0)

    def subj(x): return index.name_for(SUBJECTS, x) if x else ""
    def teach(x): return index.name_for(TEACHERS, x) if x else ""
    def room(x): return index.name_for(ROOMS, x) if x else ""

    class_id = None
    for cid, cname in CLASSES.items():
        if cname.strip().lower() == class_name.strip().lower():
            class_id = cid
            break

    if not class_id:
        return "Класс не найден"

    target_date = datetime.strptime(date_str, "%d.%m.%Y").date()

    period_id = None
    for pid, p in PERIODS.items():
        try:
            b = datetime.strptime(p["b"], "%d.%m.%Y").date()
            e = datetime.strptime(p["e"], "%d.%m.%Y").date()
            if b <= target_date <= e:
                period_id = pid
                break
        except:
            pass

    if not period_id:
        period_id = next(iter(CLASS_SCHEDULE.keys()))

    class_block = CLASS_SCHEDULE.get(period_id, {}).get(class_id, {})

    weekday = str(target_date.isoweekday())

    day_lessons = {}

    for k, v in class_block.items():
        if k.startswith(weekday):
            try:
                day_lessons[int(k[1:])] = v
            except:
                pass

    exchanges = CLASS_EXCHANGE.get(class_id, {}).get(date_str, {})

    lines = []

    lines.append(f"Расписание для {class_name}")
    lines.append(f"Дата: {date_str}")
    lines.append("")

    maxlesson = LESSONSINDAY or max(day_lessons.keys(), default=0)

    def time_txt(n):
        t = LESSON_TIMES.get(str(n))
        return f" [{t[0]}–{t[1]}]" if t else ""

    for ln in range(1, maxlesson+1):

        base = day_lessons.get(ln)
        exch = exchanges.get(str(ln))

        lesson = base
        is_replacement = False
        canceled = False

        if exch == "F":
            canceled = True

        elif isinstance(exch, dict):

            if exch.get("s") == "F":
                canceled = True
            else:
                lesson = exch
                is_replacement = True

        if not lesson:
            continue

        subjects = index.to_list(lesson.get("s"))
        teachers = index.to_list(lesson.get("t"))
        rooms = index.to_list(lesson.get("r"))

        group_count = max(len(subjects), len(teachers), len(rooms))

        if group_count == 0:
            continue

        while len(subjects) < group_count:
            subjects.append(subjects[-1])

        while len(teachers) < group_count:
            teachers.append("")

        while len(rooms) < group_count:
            rooms.append("")

        same_subject = len(set(subjects)) == 1

        header = subj(subjects[0]) + time_txt(ln)

        if canceled:
            lines.append(f"{ln}. <s>{html.escape(header)}</s>")

        elif is_replacement:
            lines.append(f"{ln}. <b>{html.escape(header)}</b>")

        else:
            lines.append(f"{ln}. {html.escape(header)}")

        if group_count == 1:

            text = teach(teachers[0])

            if rooms[0]:
                text += f" ({room(rooms[0])})"

            if canceled:
                text = f"<s>{html.escape(text)}</s>"
            else:
                text = html.escape(text)

            lines.append(f"    {text}")
            lines.append("")
            continue

        if same_subject:

            for i in range(group_count):

                text = f"Группа {i+1}: {teach(teachers[i])}"

                if rooms[i]:
                    text += f" ({room(rooms[i])})"

                if canceled:
                    text = f"<s>{html.escape(text)}</s>"
                else:
                    text = html.escape(text)

                lines.append(f"    {text}")

        else:

            for i in range(group_count):

                if i > 0:
                    lines.append("")
                    lines.append(f"    {html.escape(subj(subjects[i]))}")

                text = teach(teachers[i])

                if rooms[i]:
                    text += f" ({room(rooms[i])})"

                text += f" - Группа {i+1}"

                if canceled:
                    text = f"<s>{html.escape(text)}</s>"
                else:
                    text = html.escape(text)

                lines.append(f"    {text}")

        lines.append("")

    return "\n".join(lines)

def get_schedule(class_name: str, date: str) -> str:
    data = load_data()
    try:
        return render_schedule_html(data, class_name, date)
    except Exception as e:
        log.exception("render_schedule_html failed, falling back to text-print")
        buf = StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            index.print_schedule_for_day(data, class_name, date)
        finally:
            sys.stdout = old
        raw = buf.getvalue()
        return "<pre>" + html.escape(raw) + "</pre>"

def main_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📅 Сегодня", callback_data="today"),
                InlineKeyboardButton("📆 Завтра", callback_data="tomorrow"),
            ],
            [InlineKeyboardButton("🗓 Ввести дату", callback_data="date")],
            [InlineKeyboardButton("🎓 Сменить класс", callback_data="class")],
        ]
    )

def schedule_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎓 Сменить класс", callback_data="class")],
        ]
    )

def class_keyboard():
    data = load_data()
    classes = list(data.get("CLASSES", {}).values())
    classes = sorted(classes, key=class_natural_key)
    rows = []
    for chunk in chunk_list(classes, 3):
        row = [InlineKeyboardButton(c, callback_data=f"class|{c}") for c in chunk]
        rows.append(row)
    return InlineKeyboardMarkup(rows)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cls = context.user_data.get("class")
    if not cls:
        await update.message.reply_text("Выберите класс:", reply_markup=class_keyboard())
        return
    await update.message.reply_text(f"Класс: {cls}", reply_markup=main_keyboard())

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data.startswith("class|"):
        cls = data.split("|", 1)[1]
        context.user_data["class"] = cls
        await query.message.reply_text(f"Класс установлен: {cls}", reply_markup=main_keyboard())
        return

    if data == "class":
        await query.message.reply_text("Выберите класс:", reply_markup=class_keyboard())
        return

    if data == "date":
        context.user_data["awaiting_date"] = True
        await query.message.reply_text("Введите дату в формате DD.MM.YYYY")
        return

    if data == "today":
        date = datetime.now().strftime("%d.%m.%Y")
    elif data == "tomorrow":
        date = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
    else:
        return

    cls = context.user_data.get("class")
    if not cls:
        await query.message.reply_text("Сначала выберите класс:", reply_markup=class_keyboard())
        return

    try:
        text = get_schedule(cls, date)
    except Exception as e:
        log.exception("Ошибка при получении расписания")
        await query.message.reply_text(f"Ошибка при получении расписания: {e}")
        return

    await query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=schedule_keyboard())

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_date"):
        context.user_data["awaiting_date"] = False
        txt = update.message.text.strip()
        try:
            datetime.strptime(txt, "%d.%m.%Y")
        except Exception:
            await update.message.reply_text("Неверный формат даты. Ожидается DD.MM.YYYY")
            return
        cls = context.user_data.get("class")
        if not cls:
            await update.message.reply_text("Класс не установлен. Сначала выберите класс:", reply_markup=class_keyboard())
            return
        try:
            text = get_schedule(cls, txt)
        except Exception as e:
            log.exception("Ошибка при получении расписания")
            await update.message.reply_text(f"Ошибка при получении расписания: {e}")
            return
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())
        return
    await update.message.reply_text("Используйте кнопки для взаимодействия. /start")


def main():
    download_js()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    log.info("Bot started (polling)...")
    app.run_polling()

if __name__ == "__main__":
    main()
