# Отправляет пост в Telegram-канал: текст (HTML) и, если есть, викторину.
# Формат: {"text": "...", "quiz": {"question": "...", "options": [...], "correct": 0, "explanation": "..."}}
#   или     {"task": "004", "quiz": {...}} — текст задачи собирается из sql/tasks.json + кнопка «Решить в тренажёре»
#   кнопка к обычному тексту: "button": {"text": "...", "url": "..."}
# Запуск вручную: python3 telegram.py telegram/welcome.json
import json, os, re, sys, pathlib, urllib.request, urllib.error

TOKEN = os.environ.get("TG_TOKEN", "").strip()
CHAT = os.environ.get("TG_CHAT", "@sqlsenior")
TRAINER = "https://seniorsql.github.io/seniorsql-media/sql/"
TASKS = pathlib.Path(__file__).parent / "sql" / "tasks.json"


def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def md(t):
    # `код` -> <code>, **жирный** -> <b>
    t = esc(t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)


def plain(t):
    return str(t).replace("**", "").replace("`", "")


def grid(columns, rows):
    # таблица моноширинным шрифтом для <pre>
    cells = [[str(c) for c in columns]] + [["NULL" if v is None else str(v) for v in r] for r in rows]
    w = [max(len(r[i]) for r in cells) for i in range(len(columns))]
    line = lambda r: " | ".join(v.ljust(w[i]) for i, v in enumerate(r)).rstrip()
    out = [line(cells[0]), "-+-".join("-" * x for x in w)] + [line(r) for r in cells[1:]]
    return "<pre>" + esc("\n".join(out)) + "</pre>"


def start_text(t):
    # простая задача для новичков, без номеров шагов и уроков (13.11.2026: «просто бесконечный поток»)
    parts = [f"<b>🧩 Задача · {esc(t['topic'])}</b>", f"{esc(t['title'])}", ""]
    for tb in t["tables"]:
        parts += [f"📋 Таблица <code>{esc(tb['name'])}</code>:", grid(tb["columns"], tb["rows"])]
    parts += [f"✍️ <b>Задание:</b> {md(t['question'])}", ""]
    parts += ["✅ <b>Должно получиться:</b>", grid(t["expected"]["columns"], t["expected"]["rows"])]
    hints = t.get("hints") or ([t["hint"]] if t.get("hint") else [])
    if hints:
        steps = " ".join(f"{i}) {plain(h)}" for i, h in enumerate(hints, 1))
        parts += [f"💡 Подсказка: <tg-spoiler>{esc(steps)}</tg-spoiler>", ""]
    parts += [f"🔒 Ответ: <tg-spoiler>{esc(' '.join(t['solution'].split()))}</tg-spoiler>"]
    parts += ["", "👇 Реши в тренажёре — он сам проверит. Ошибёшься — подскажет, что не так."]
    return "\n".join(parts)


def task_text(task_id):
    tasks = json.loads(TASKS.read_text(encoding="utf-8"))["tasks"]
    t = next(x for x in tasks if x["id"] == task_id)
    if t.get("section") == "start":
        return start_text(t), TRAINER + "#" + t["id"]
    parts = [f"<b>🧩 Задача дня · {esc(t['topic'])}</b>", ""]
    for tb in t["tables"]:
        parts += [f"📋 <b>Дано</b> — таблица <code>{esc(tb['name'])}</code>:", grid(tb["columns"], tb["rows"])]
    parts += [f"❓ <b>Задание:</b> {md(t['question'])}", ""]
    label = t["expected"].get("label")
    parts += [f"✅ <b>Должно получиться{': ' + esc(label) if label else ''}:</b>", grid(t["expected"]["columns"], t["expected"]["rows"])]
    if t.get("hint"):
        parts += [f"💡 Подсказка: <tg-spoiler>{esc(plain(t['hint']))}</tg-spoiler>", ""]
    answer = " ".join(t["solution"].split())
    if t.get("explain"):
        answer += "\n" + plain(t["explain"])
    parts += [f"🔒 Ответ: <tg-spoiler>{esc(answer)}</tg-spoiler>"]
    parts += ["", "✍️ Напиши запрос в тренажёре — он сам проверит, верно ли 👇"]
    return "\n".join(parts), TRAINER + "#" + t["id"]


def call(method, **params):
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}",
                                 data=json.dumps(params).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)["result"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Ошибка Telegram ({method}): {e.read().decode()}")


def reel(meta, video_url):
    # ролик из Instagram + викторина с теми же вариантами ответа
    if not TOKEN:
        print("TG_TOKEN не задан — Telegram пропущен")
        return
    caption = f"🎬 <b>{esc(plain(meta['hook']))}</b>\n\nСмотри ролик и отвечай в викторине ниже 👇"
    call("sendVideo", chat_id=CHAT, video=video_url, caption=caption, parse_mode="HTML", supports_streaming=True,
         width=1080, height=1920)
    code = meta["code"]
    question = (plain(meta.get("question") or "Что выведет запрос?") + "\n\n" + code)[:300]
    call("sendPoll", chat_id=CHAT, question=question, options=[{"text": plain(o)[:100]} for o in meta["options"]],
         type="quiz", correct_option_id=meta["correct"], explanation=plain(meta.get("explain", ""))[:200], is_anonymous=True)
    print(f"Telegram: ролик и викторина отправлены в {CHAT}")


def send(tg, pin=False):
    if not TOKEN:
        print("TG_TOKEN не задан — Telegram пропущен")
        return
    text, button = tg.get("text"), tg.get("button")
    if tg.get("task"):
        text, url = task_text(tg["task"])
        button = {"text": "✍️ Решить в тренажёре", "url": url}
    if text and tg.get("edit"):
        # "edit": номер сообщения — исправить уже опубликованный пост, а не слать новый
        extra = {"reply_markup": {"inline_keyboard": [[button]]}} if button else {}
        call("editMessageText", chat_id=CHAT, message_id=tg["edit"], text=text, parse_mode="HTML",
             link_preview_options={"is_disabled": True}, **extra)
        print(f"Telegram: исправлено сообщение {tg['edit']} в {CHAT}")
        return
    if text:
        extra = {"reply_markup": {"inline_keyboard": [[button]]}} if button else {}
        msg = call("sendMessage", chat_id=CHAT, text=text, parse_mode="HTML", link_preview_options={"is_disabled": True}, **extra)
        if pin:
            if tg.get("unpin_old"):
                call("unpinAllChatMessages", chat_id=CHAT)  # старое закреплённое сообщение снимаем
            call("pinChatMessage", chat_id=CHAT, message_id=msg["message_id"], disable_notification=True)
    quiz = tg.get("quiz")
    if quiz:
        call("sendPoll", chat_id=CHAT, question=quiz["question"], options=[{"text": o} for o in quiz["options"]],
             type="quiz", correct_option_id=quiz["correct"], explanation=quiz.get("explanation", ""), is_anonymous=True)
    print(f"Telegram: отправлено в {CHAT}")


if __name__ == "__main__":
    data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    send(data, pin=data.get("pin", False))
