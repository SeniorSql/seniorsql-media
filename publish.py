# Публикует следующий пост-карусель из папки posts/ в Instagram.
# Запускается роботом GitHub Actions по расписанию (.github/workflows/publish.yml).
import json, os, sys, time, pathlib, urllib.request, urllib.parse, urllib.error

API = "https://graph.facebook.com/v23.0"
TOKEN = os.environ["IG_TOKEN"]
IG = os.environ["IG_USER_ID"]
REPO = os.environ["GITHUB_REPOSITORY"]
BRANCH = os.environ.get("GITHUB_REF_NAME", "main")

root = pathlib.Path("posts")
done_file = pathlib.Path("published.txt")
done = set(done_file.read_text(encoding="utf-8").split()) if done_file.exists() else set()


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
        sys.exit(f"Ошибка Meta API ({path}): {e.read().decode()}")


def wait_ready(container_id):
    for _ in range(30):
        status = call("GET", container_id, fields="status_code")["status_code"]
        if status == "FINISHED":
            return
        if status == "ERROR":
            sys.exit(f"Instagram не смог обработать {container_id}")
        time.sleep(5)
    sys.exit(f"Instagram слишком долго обрабатывает {container_id}")


if os.environ.get("POST"):
    queue = [root / os.environ["POST"]]
else:
    queue = sorted(p for p in root.iterdir() if p.is_dir() and p.name not in done and (p / "post.json").exists())
if not queue:
    print("Очередь пуста — нет готовых постов")
    sys.exit(0)

post = queue[0]
meta = json.loads((post / "post.json").read_text(encoding="utf-8"))
images = sorted(post.glob("*.jpg"))
if not 2 <= len(images) <= 10:
    sys.exit(f"{post.name}: в карусели должно быть 2–10 картинок, а их {len(images)}")

children = []
for img in images:
    url = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{img.as_posix()}"
    cid = call("POST", f"{IG}/media", image_url=url, is_carousel_item="true")["id"]
    wait_ready(cid)
    children.append(cid)

carousel = call("POST", f"{IG}/media", media_type="CAROUSEL", children=",".join(children), caption=meta["caption"])["id"]
wait_ready(carousel)
media_id = call("POST", f"{IG}/media_publish", creation_id=carousel)["id"]
link = call("GET", media_id, fields="permalink").get("permalink", "")

with done_file.open("a", encoding="utf-8") as f:
    f.write(post.name + "\n")
print(f"Опубликовано: {post.name} {link}")
