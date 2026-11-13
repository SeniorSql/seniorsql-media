# Публикует следующий пост: карусель в Instagram и задачу с викториной в Telegram.
# Instagram и Telegram идут независимо — у каждого своя очередь (published.txt и telegram_sent.txt),
# поэтому сбой одной соцсети не останавливает другую.
# Запускается роботом GitHub Actions по расписанию (.github/workflows/publish.yml).
import json, os, sys, time, pathlib, urllib.request, urllib.parse, urllib.error

API = "https://graph.facebook.com/v23.0"
TOKEN = os.environ.get("IG_TOKEN", "")
IG = os.environ.get("IG_USER_ID", "")
BUFFER = os.environ.get("BUFFER_TOKEN", "").strip()  # если есть — Instagram публикуется через Buffer
REPO = os.environ["GITHUB_REPOSITORY"]
BRANCH = os.environ.get("GITHUB_REF_NAME", "main")

root = pathlib.Path("posts")
ig_file = pathlib.Path("published.txt")
tg_file = pathlib.Path("telegram_sent.txt")


def done(path):
    return set(path.read_text(encoding="utf-8").split()) if path.exists() else set()


def mark(path, name):
    with path.open("a", encoding="utf-8") as f:
        f.write(name + "\n")


def queue(skip):
    return sorted(p for p in root.iterdir() if p.is_dir() and p.name not in skip and (p / "post.json").exists())


def load(post):
    return json.loads((post / "post.json").read_text(encoding="utf-8"))


def call(method, path, **params):
    params["access_token"] = TOKEN
    data = urllib.parse.urlencode(params)
    if method == "GET":
        req = urllib.request.Request(f"{API}/{path}?{data}")
    else:
        req = urllib.request.Request(f"{API}/{path}", data=data.encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Ошибка Meta API ({path}): {e.read().decode()}")


def wait_ready(container_id):
    for _ in range(30):
        status = call("GET", container_id, fields="status_code")["status_code"]
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Instagram не смог обработать {container_id}")
        time.sleep(5)
    raise RuntimeError(f"Instagram слишком долго обрабатывает {container_id}")


def instagram(post):
    meta = load(post)
    images = sorted(post.glob("*.jpg"))
    if not 2 <= len(images) <= 10:
        raise RuntimeError(f"{post.name}: в карусели должно быть 2–10 картинок, а их {len(images)}")
    children = []
    for img in images:
        url = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{img.as_posix()}"
        cid = call("POST", f"{IG}/media", image_url=url, is_carousel_item="true")["id"]
        wait_ready(cid)
        children.append(cid)
    carousel = call("POST", f"{IG}/media", media_type="CAROUSEL", children=",".join(children), caption=meta["caption"])["id"]
    wait_ready(carousel)
    media_id = call("POST", f"{IG}/media_publish", creation_id=carousel)["id"]
    return call("GET", media_id, fields="permalink").get("permalink", "")


def buffer_call(query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request("https://api.buffer.com", data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {BUFFER}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Ошибка Buffer API: {e.code} {e.read().decode()}")
    if res.get("errors"):
        raise RuntimeError(f"Ошибка Buffer API: {res['errors']}")
    return res["data"]


def buffer_instagram(post):
    meta = load(post)
    images = sorted(post.glob("*.jpg"))
    if not 2 <= len(images) <= 10:
        raise RuntimeError(f"{post.name}: в карусели должно быть 2–10 картинок, а их {len(images)}")
    orgs = buffer_call("query { account { organizations { id } } }")["account"]["organizations"]
    channel = None
    for org in orgs:
        chans = buffer_call("query($o: OrganizationId!) { channels(input: {organizationId: $o}) { id service name } }",
                            {"o": org["id"]})["channels"]
        channel = next((c for c in chans if c["service"].lower() == "instagram"), None)
        if channel:
            break
    if not channel:
        raise RuntimeError("В Buffer не подключён Instagram")
    urls = [f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{img.as_posix()}" for img in images]
    res = buffer_call("""mutation($input: CreatePostInput!) { createPost(input: $input) {
        ... on PostActionSuccess { post { id status } }
        ... on MutationError { message } } }""", {"input": {
        "text": meta["caption"], "channelId": channel["id"], "schedulingType": "automatic", "mode": "shareNow",
        "assets": [{"image": {"url": u}} for u in urls],
        "metadata": {"instagram": {"type": "post", "shouldShareToFeed": True}}}})["createPost"]
    if "message" in res:
        raise RuntimeError(f"Buffer отказал: {res['message']}")
    return f"Buffer, пост {res['post']['id']} ({res['post']['status']})"


PAGES = "https://seniorsql.github.io/seniorsql-media"  # mp4 отдаём с GitHub Pages (правильный тип video/mp4)
reels_root = pathlib.Path("reels")
reels_file = pathlib.Path("reels_published.txt")


def buffer_channel():
    for org in buffer_call("query { account { organizations { id } } }")["account"]["organizations"]:
        chans = buffer_call("query($o: OrganizationId!) { channels(input: {organizationId: $o}) { id service name } }",
                            {"o": org["id"]})["channels"]
        ch = next((c for c in chans if c["service"].lower() == "instagram"), None)
        if ch:
            return ch
    raise RuntimeError("В Buffer не подключён Instagram")


def buffer_reel(reel):
    meta = json.loads((reel / "reel.json").read_text(encoding="utf-8"))
    base = f"{PAGES}/reels/{reel.name}"
    res = buffer_call("""mutation($input: CreatePostInput!) { createPost(input: $input) {
        ... on PostActionSuccess { post { id status } }
        ... on MutationError { message } } }""", {"input": {
        "text": meta["caption"], "channelId": buffer_channel()["id"], "schedulingType": "automatic", "mode": "shareNow",
        # обложка — кадр-крючок на 0,5 с (свою картинку соцсети не принимают)
        "assets": [{"video": {"url": f"{base}/reel.mp4", "metadata": {"thumbnailOffset": 500}}}],
        "metadata": {"instagram": {"type": "reel", "shouldShareToFeed": True}}}})["createPost"]
    if "message" in res:
        raise RuntimeError(f"Buffer отказал: {res['message']}")
    return f"Buffer, пост {res['post']['id']} ({res['post']['status']})"


failed = False

# 0. Reels — следующий готовый ролик ("ready": true), если этот запуск — слот для Reels
if BUFFER and os.environ.get("REEL_SLOT") == "true" and reels_root.exists():
    sent = done(reels_file)
    ready = [r for r in sorted(reels_root.iterdir()) if r.is_dir() and r.name not in sent and (r / "reel.json").exists()
             and json.loads((r / "reel.json").read_text(encoding="utf-8")).get("ready")]
    if not ready:
        print("Reels: очередь пуста")
    else:
        try:
            print(f"Reels: опубликовано {ready[0].name} {buffer_reel(ready[0])}")
            mark(reels_file, ready[0].name)
        except Exception as e:
            print(f"::error::Reels ({ready[0].name}): {e}")
            failed = True

# 0б. Ролики в Telegram — ВЫКЛЮЧЕНО 13.11.2026 по решению Этибара (в Telegram ролики не нужны).
# Включается только переменной TG_REELS=1 в publish.yml.
tg_reels_file = pathlib.Path("telegram_reels_sent.txt")
if os.environ.get("TG_REELS") == "1" and os.environ.get("TG_TOKEN") and os.environ.get("REEL_SLOT") == "true" and reels_file.exists():
    import telegram
    out = [n for n in reels_file.read_text(encoding="utf-8").split() if (reels_root / n / "reel.json").exists()]
    todo = [n for n in out if n not in done(tg_reels_file)]
    if todo:
        name = todo[-1]
        try:
            telegram.reel(json.loads((reels_root / name / "reel.json").read_text(encoding="utf-8")),
                          f"{PAGES}/reels/{name}/reel.mp4")
            for n in todo:  # старые ролики в Telegram не догоняем — отмечаем все
                mark(tg_reels_file, n)
        except Exception as e:
            print(f"::error::Telegram, ролик {name}: {e}")
            failed = True

# 1. Instagram
ig_queue = [root / os.environ["POST"]] if os.environ.get("POST") else queue(done(ig_file))
if os.environ.get("IG_PAUSE") == "1" and not os.environ.get("POST"):
    print("Instagram: карусели на паузе (IG_PAUSE=1)")
elif not ig_queue:
    print("Instagram: очередь пуста — нет готовых постов")
else:
    post = ig_queue[0]
    try:
        link = buffer_instagram(post) if BUFFER else instagram(post)
        mark(ig_file, post.name)
        print(f"Instagram: опубликовано {post.name} {link}")
    except Exception as e:
        print(f"::error::Instagram ({post.name}): {e}")
        failed = True

# 2. Telegram — следующая задача «Старт с нуля» из sql/tasks.json (с 14.11.2026 — в каждом запуске: 12:00 и 19:00)
if os.environ.get("TG_TOKEN"):
    import telegram
    sent = done(tg_file)
    tasks = json.loads(pathlib.Path("sql/tasks.json").read_text(encoding="utf-8"))["tasks"]
    start = [t["id"] for t in tasks if t.get("section") == "start" and t["id"] not in sent]
    if start:
        try:
            telegram.send({"task": start[0]})
            mark(tg_file, start[0])
            print(f"Telegram: задача {start[0]}")
        except Exception as e:
            print(f"::error::Telegram (задача {start[0]}): {e}")
            failed = True
    else:
        print("::warning::Telegram: задачи «Старт с нуля» закончились — нужны новые в sql/tasks.json")

# 2б. Старая очередь постов-каруселей (все уже отправлены, оставлено на случай новых постов)
if os.environ.get("TG_TOKEN") and os.environ.get("REEL_SLOT") != "true" and False:
    import telegram
    for post in queue(done(tg_file)):
        tg = load(post).get("telegram")
        if not tg:
            mark(tg_file, post.name)  # у поста нет задачи для Telegram — пропускаем
            continue
        try:
            telegram.send(tg)
            mark(tg_file, post.name)
            print(f"Telegram: отправлено {post.name}")
        except Exception as e:
            print(f"::error::Telegram ({post.name}): {e}")
            failed = True
        break
    else:
        print("Telegram: очередь пуста")

sys.exit(1 if failed else 0)
