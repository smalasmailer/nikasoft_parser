import argparse
import json
import re
import sys
from datetime import datetime
from urllib.request import urlopen

def load_source(file_path=None, url=None):
    if url:
        with urlopen(url) as r:
            return r.read().decode("utf-8")
    if file_path:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise RuntimeError("No input source: give --file PATH or --url URL or pipe data via stdin")


def extract_nika_json(js_text):
    m = re.search(r'\bvar\s+NIKA\s*=', js_text)
    if not m:
        raise ValueError("var NIKA = ... not found in input")
    i = m.end()
    while i < len(js_text) and js_text[i] not in '{':
        i += 1
    if i >= len(js_text):
        raise ValueError("opening { for NIKA not found")
    start = i
    depth = 0
    in_str = False
    esc = False
    quote = None
    for j in range(start, len(js_text)):
        ch = js_text[j]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == quote:
                in_str = False
                quote = None
            continue
        else:
            if ch == '"' or ch == "'":
                in_str = True
                quote = ch
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    json_text = js_text[start:j+1]
                    try:
                        return json.loads(json_text)
                    except json.JSONDecodeError as e:
                        raise ValueError(f"JSON parse error: {e}")
    raise ValueError("Could not find matching closing } for NIKA object")

def to_list(maybe):
    if maybe is None:
        return []
    if isinstance(maybe, list):
        return [x for x in maybe if x != "" and x is not None]
    if isinstance(maybe, str):
        if maybe == "":
            return []
        return [maybe]
    return [maybe]

def name_for(mapping, key):
    if key is None:
        return ""
    return mapping.get(key, key)

def print_schedule_for_day(data, class_name, date_str):

    CLASSES = data.get("CLASSES", {})
    SUBJECTS = data.get("SUBJECTS", {})
    TEACHERS = data.get("TEACHERS", {})
    ROOMS = data.get("ROOMS", {})
    CLASS_SCHEDULE = data.get("CLASS_SCHEDULE", {})
    CLASS_EXCHANGE = data.get("CLASS_EXCHANGE", {})
    LESSON_TIMES = data.get("LESSON_TIMES", {})
    LESSONSINDAY = data.get("LESSONSINDAY", 0)

    def subject_name(x):
        return SUBJECTS.get(x, x)

    def teacher_name(x):
        return TEACHERS.get(x, x)

    def room_name(x):
        return ROOMS.get(x, x)

    class_id = None
    for cid, cname in CLASSES.items():
        if cname == class_name:
            class_id = cid

    if not class_id:
        print("Класс не найден")
        return

    target_date = datetime.strptime(date_str, "%d.%m.%Y").date()

    weekday = str(target_date.isoweekday())

    period_id = next(iter(CLASS_SCHEDULE.keys()))

    class_block = CLASS_SCHEDULE[period_id][class_id]

    day_lessons = {}

    for k, v in class_block.items():
        if k.startswith(weekday):
            day_lessons[int(k[1:])] = v

    exch = CLASS_EXCHANGE.get(class_id, {}).get(date_str, {})

    maxlesson = LESSONSINDAY or max(day_lessons.keys(), default=0)

    for ln in range(1, maxlesson + 1):

        lesson = day_lessons.get(ln)

        ex = exch.get(str(ln))

        if isinstance(ex, dict):

            s = ex.get("s")
            t = ex.get("t")
            r = ex.get("r")

            if isinstance(s, dict):

                for g in s:

                    print(f"{ln}. {subject_name(s[g])}")
                    teach = ", ".join(teacher_name(x) for x in to_list(t[g]))
                    room = ", ".join(room_name(x) for x in to_list(r[g]))

                    print(f"    {teach} ({room}) - Группа {g}")
                    print()

                continue

            if isinstance(t, dict):

                subj = ", ".join(subject_name(x) for x in to_list(s))

                print(f"{ln}. {subj}")

                for g in t:

                    teach = ", ".join(teacher_name(x) for x in to_list(t[g]))
                    room = ", ".join(room_name(x) for x in to_list(r[g]))

                    print(f"    Группа {g}: {teach} ({room})")

                print()
                continue

        if not lesson:
            continue

        s = lesson.get("s")
        t = lesson.get("t")
        r = lesson.get("r")

        if isinstance(s, dict):

            for g in s:

                print(f"{ln}. {subject_name(s[g])}")
                teach = ", ".join(teacher_name(x) for x in to_list(t[g]))
                room = ", ".join(room_name(x) for x in to_list(r[g]))

                print(f"    {teach} ({room}) - Группа {g}")
                print()

            continue

        if isinstance(t, dict):

            subj = ", ".join(subject_name(x) for x in to_list(s))

            print(f"{ln}. {subj}")

            for g in t:

                teach = ", ".join(teacher_name(x) for x in to_list(t[g]))
                room = ", ".join(room_name(x) for x in to_list(r[g]))

                print(f"    Группа {g}: {teach} ({room})")

            print()
            continue

        subj = ", ".join(subject_name(x) for x in to_list(s))
        teach = ", ".join(teacher_name(x) for x in to_list(t))
        room = ", ".join(room_name(x) for x in to_list(r))

        print(f"{ln}. {subj}")
        print(f"    {teach} ({room})")
        print()

def main():
    parser = argparse.ArgumentParser(description="Просмотр расписания Ника-Софт")
    parser.add_argument("--file", "-f", help="Путь к локальному скрипту JS с расписанием")
    parser.add_argument("--url", "-u", help="Ссылка на скрипт JS с расписанием")
    parser.add_argument("--class", "-c", dest="classname", help='Класс (например, 5а)', default=None)
    parser.add_argument("--date", "-d", help="Дата в формате ДД.ММ.ГГГГ (необязательно)")
    args = parser.parse_args()

    try:
        txt = load_source(file_path=args.file, url=args.url)
    except Exception as e:
        print("Ошибка чтения источника:", e)
        sys.exit(1)

    try:
        data = extract_nika_json(txt)
    except Exception as e:
        print("Ошибка извлечения JSON:", e)
        sys.exit(1)

    date_str = args.date
    if not date_str:
        ed = data.get("EXPORT_DATE")
        if ed:
            try:
                _ = datetime.strptime(ed, "%d.%m.%Y")
                date_str = ed
            except:
                try:
                    date_str = datetime.strptime(ed, "%Y-%m-%d").strftime("%d.%m.%Y")
                except:
                    date_str = None
    if not date_str:
        print("Дата не указана. Укажите --date ДД.MM.ГГГГ или убедитесь, что в файле есть EXPORT_DATE.")
        sys.exit(1)

    classname = args.classname
    if not classname:
        classes = data.get("CLASSES", {})
        if classes:
            classname = next(iter(classes.values()))
            print(f"Класс не указан. Использую первый класс из файла: {classname}")
        else:
            print("Класс не указан и в файле нет списка CLASSES. Укажите --class.")
            sys.exit(1)

    print_schedule_for_day(data, classname, date_str)

if __name__ == "__main__":
    main()
