# Отправляет пост в Telegram-канал: текст (HTML) и, если есть, викторину.
# Формат: {"text": "...", "quiz": {"question": "...", "options": [...], "correct": 0, "explanation": "..."}}
# Запуск вручную: python3 telegram.py telegram/welcome.json
import json, os, sys, pathlib, urllib.request, urllib.error

TOKEN = os.environ.get("TG_TOKEN", "").strip()
CHAT = os.environ.get("TG_CHAT", "@sqlsenior")


def call(method, **params):
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}",
                                 data=json.dumps(params).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)["result"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Ошибка Telegram ({method}): {e.read().decode()}")


def send(tg, pin=False):
    if not TOKEN:
        print("TG_TOKEN не задан — Telegram пропущен")
        return
    if tg.get("text"):
        msg = call("sendMessage", chat_id=CHAT, text=tg["text"], parse_mode="HTML", link_preview_options={"is_disabled": True})
        if pin:
            call("pinChatMessage", chat_id=CHAT, message_id=msg["message_id"], disable_notification=True)
    quiz = tg.get("quiz")
    if quiz:
        call("sendPoll", chat_id=CHAT, question=quiz["question"], options=[{"text": o} for o in quiz["options"]],
             type="quiz", correct_option_id=quiz["correct"], explanation=quiz.get("explanation", ""), is_anonymous=True)
    print(f"Telegram: отправлено в {CHAT}")


if __name__ == "__main__":
    data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    send(data, pin=data.get("pin", False))
