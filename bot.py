import logging
import html
import re
import sys
import index
from io import StringIO
from datetime import datetime, timedelta
from typing import Any, Dict, List
import urllib.request
import urllib.parse

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
JS_FILE = "nika_data.js"
BASE_URL = "https://raspisanie.nikasoft.ru"
SCHOOL_ID = "..."

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

def get_latest_js_url():

    url = f"https://raspisanie.nikasoft.ru/{SCHOOL_ID}.html"

    with urllib.request.urlopen(url) as r:
        html = r.read().decode("utf-8")

    match = re.search(
        rf"/static/public/{SCHOOL_ID}_\d+\.js",
        html
    )

    if not match:
        raise RuntimeError("JS not found")

    return "https://raspisanie.nikasoft.ru" + match.group(0)


def download_js():

    try:
        js_url = get_latest_js_url()
    except Exception as e:
        log.error(f"Failed to get latest JS URL: {e}")
        raise

    log.info("Downloading JS...")

    text = index.load_source(url=js_url)

    with open(JS_FILE, "w", encoding="utf-8") as f:
        f.write(text)

    log.info("JS downloaded successfully")

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

def format_export_datetime(data: Dict[str, Any]) -> str:

    export_date = data.get("EXPORT_DATE")
    export_time = data.get("EXPORT_TIME")

    if not export_date or not export_time:
        return ""

    try:
        dt = datetime.strptime(
            export_date + " " + export_time,
            "%d.%m.%Y %H:%M:%S"
        )
    except:
        return ""

    now = datetime.now()

    today = now.date()
    yesterday = today - timedelta(days=1)

    if dt.date() == today:
        prefix = "сегодня"
    elif dt.date() == yesterday:
        prefix = "вчера"
    else:
        prefix = dt.strftime("%d.%m.%Y")

    time_str = dt.strftime("%H:%M")

    return f"Обновлено: {prefix} в {time_str}"


def render_schedule_html(data: Dict[str, Any], class_name: str, date_str: str) -> str:
    CLASSGROUPS = data.get("CLASSGROUPS", {})
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
    def group_name(g):
        if g is None or g == "":
            return ""

        g = str(g)

        if g in CLASSGROUPS:
            return CLASSGROUPS[g]

        # fallback
        if g.isdigit():
            return f"Группа {int(g)+1}"

        return g


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

            # отменён весь урок
            lesson = base
            canceled = True

        elif isinstance(exch, dict):

            # если отменён весь урок
            if exch.get("s") == "F":

                lesson = base
                canceled = True

            else:

                # merge exchange в base
                lesson = dict(base) if base else {}

                for key in ("s", "t", "r"):

                    exch_val = exch.get(key)
                    base_val = lesson.get(key)

                    if isinstance(exch_val, dict) and isinstance(base_val, dict):

                        merged = dict(base_val)

                        for g, v in exch_val.items():

                            merged[g] = v

                        lesson[key] = merged

                    else:

                        lesson[key] = exch_val

                is_replacement = True

        if not lesson:
            continue

        if isinstance(lesson.get("s"), dict) or isinstance(lesson.get("t"), dict):
            s_dict = lesson.get("s") or {}
            t_dict = lesson.get("t") or {}
            r_dict = lesson.get("r") or {}

            groups = sorted(set(s_dict) | set(t_dict) | set(r_dict))

            # найти первый НЕ отменённый предмет для заголовка
            first_subj = None
            for g in groups:
                sg = s_dict.get(g)
                if sg and sg != "F":
                    first_subj = subj(sg)
                    break

            if not first_subj:
                first_subj = "урок"

            header = first_subj + time_txt(ln)

            if canceled:
                lines.append(f"{ln}. <s>{html.escape(header)}</s>")
            elif is_replacement:
                lines.append(f"{ln}. <b>{html.escape(header)}</b>")
            else:
                lines.append(f"{ln}. {html.escape(header)}")

            for g in groups:

                sg = s_dict.get(g)
                tg = t_dict.get(g)
                rg = r_dict.get(g)

                group_canceled = (
                    sg == "F"
                    or tg == "F"
                    or rg == "F"
                    or sg == ""
                    or tg == ""
                )

                group_name = f"Группа {g}"

                if sg and sg != "F":
                    group_name += f": {subj(sg)}"

                teacher = teach(tg) if tg and tg != "F" else ""
                roomtxt = room(rg) if rg and rg != "F" else ""

                text = group_name

                if teacher:
                    text += f" - {teacher}"

                if roomtxt:
                    text += f" ({roomtxt})"

                if group_canceled:
                    text = f"<s>{html.escape(text)}</s>"
                else:
                    text = html.escape(text)

                lines.append(f"    {text}")

            lines.append("")
            continue

        groups = lesson.get("g")
        subjects = index.to_list(lesson.get("s"))
        teachers = index.to_list(lesson.get("t"))
        rooms = index.to_list(lesson.get("r"))

        # если групп нет - обычный урок
        if not groups:

            header = subj(subjects[0]) + time_txt(ln)

            if canceled:
                lines.append(f"{ln}. <s>{html.escape(header)}</s>")
            elif is_replacement:
                lines.append(f"{ln}. <b>{html.escape(header)}</b>")
            else:
                lines.append(f"{ln}. {html.escape(header)}")

            teacher = teach(teachers[0]) if teachers else ""
            roomtxt = room(rooms[0]) if rooms else ""

            text = teacher
            if roomtxt:
                text += f" ({roomtxt})"

            if canceled:
                text = f"<s>{html.escape(text)}</s>"
            else:
                text = html.escape(text)

            lines.append(f"    {text}")
            lines.append("")
            continue


        # если группы есть
        groups = index.to_list(groups)

        group_count = max(len(groups), len(subjects), len(teachers), len(rooms))

        while len(subjects) < group_count:
            subjects.append("")

        while len(teachers) < group_count:
            teachers.append("")

        while len(rooms) < group_count:
            rooms.append("")

        # вывод групп
        unique_subjects = set(x for x in subjects if x)
        same_subject = len(unique_subjects) == 1

        # если предмет одинаковый → нормальный заголовок
        if same_subject:

            header = subj(subjects[0]) + time_txt(ln)

            if canceled:
                lines.append(f"{ln}. <s>{html.escape(header)}</s>")
            elif is_replacement:
                lines.append(f"{ln}. <b>{html.escape(header)}</b>")
            else:
                lines.append(f"{ln}. {html.escape(header)}")

            for i in range(group_count):

                g_raw = groups[i]
                g_name = group_name(g_raw)

                text = g_name

                t = teachers[i]
                r = rooms[i]

                canceled_group = (t == "")

                text = f"{g_name}"

                if t:
                    text += f" - {teach(t)}"

                if r:
                    text += f" ({room(r)})"

                if canceled_group:
                    text = f"<s>{html.escape(text)}</s>"
                else:
                    text = html.escape(text)

                lines.append(f"    {text}")

            lines.append("")
            continue


        # если предмет разный → без заголовка предмета
        else:
            for i in range(group_count):

                g_raw = groups[i]   # ← берём raw значение из JSON
                g_name = group_name(g_raw)

                s = subjects[i]
                t = teachers[i]
                r = rooms[i]

                canceled_group = (s == "" or t == "")

                text = ""

                if i == 0:
                    text += f"{ln}.\n"

                text += f"   {g_name}: {subj(s)}"

                if t:
                    text += f" - {teach(t)}"

                if r:
                    text += f" ({room(r)})"

                # время только у последней группы
                if i == group_count - 1:
                    text += time_txt(ln)

                if canceled_group:
                    text = f"   <s>{html.escape(text)}</s>"
                else:
                    text = html.escape(text)

                lines.append(text)

            lines.append("")
            continue

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

    data = load_data()
    updated = format_export_datetime(data)

    cls = context.user_data.get("class")

    if not cls:

        text = "Выберите класс:"
        if updated:
            text = updated + "\n\n" + text

        await update.message.reply_text(
            text,
            reply_markup=class_keyboard()
        )
        return

    text = f"Класс: {cls}"

    if updated:
        text = updated + "\n\n" + text

    await update.message.reply_text(
        text,
        reply_markup=main_keyboard()
    )

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data.startswith("class|"):
        cls = data.split("|", 1)[1]
        context.user_data["class"] = cls

        data_json = load_data()
        updated = format_export_datetime(data_json)

        text = f"Расписание для {cls}"

        if updated:
            text = updated + "\n\n" + text

        await query.message.reply_text(
            text,
            reply_markup=main_keyboard()
        )

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

    data_json = load_data()

    await query.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=schedule_keyboard()
    )

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


async def auto_update(context: ContextTypes.DEFAULT_TYPE):
    try:
        download_js()
        log.info("Schedule auto-updated")
    except Exception as e:
        log.error(f"Auto update failed: {e}")


def main():

    download_js()

    app = Application.builder().token(TOKEN).build()

    # безопасная проверка JobQueue
    if app.job_queue is None:
        log.warning("JobQueue not available. Install apscheduler to enable auto-update.")
    else:
        app.job_queue.run_repeating(
            auto_update,
            interval=300,
            first=300
        )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    log.info("Bot started")

    app.run_polling()


if __name__ == "__main__":
    main()
