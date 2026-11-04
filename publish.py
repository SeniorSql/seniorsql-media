# Публикует следующий пост: карусель в Instagram и задачу с викториной в Telegram.
# Instagram и Telegram идут независимо — у каждого своя очередь (published.txt и telegram_sent.txt),
# поэтому сбой одной соцсети не останавливает другую.
# Запускается роботом GitHub Actions по расписанию (.github/workflows/publish.yml).
import json, os, sys, time, pathlib, urllib.request, urllib.parse, urllib.error

API = "https://graph.facebook.com/v23.0"
TOKEN = os.environ["IG_TOKEN"]
IG = os.environ["IG_USER_ID"]
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


failed = False

# 1. Instagram
ig_queue = [root / os.environ["POST"]] if os.environ.get("POST") else queue(done(ig_file))
if not ig_queue:
    print("Instagram: очередь пуста — нет готовых постов")
else:
    post = ig_queue[0]
    try:
        link = instagram(post)
        mark(ig_file, post.name)
        print(f"Instagram: опубликовано {post.name} {link}")
    except Exception as e:
        print(f"::error::Instagram ({post.name}): {e}")
        failed = True

# 2. Telegram — следующий пост, к которому есть задача
if os.environ.get("TG_TOKEN"):
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
