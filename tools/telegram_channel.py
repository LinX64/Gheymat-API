import datetime
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

CHANNEL = os.environ.get("TELEGRAM_CHANNEL", "@gheymat_fresh")
ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_icon.png")

IOS_SHORT = "https://apps.apple.com/app/id6823214886"
IOS_CAMPAIGN = "https://apps.apple.com/app/apple-store/id6823214886?pt=129247156&ct=telegram-channel&mt=8"
IOS_REVIEW = "https://apps.apple.com/app/id6823214886?action=write-review"
PLAY_SHORT = "https://play.google.com/store/apps/details?id=com.gheymat.app"
PLAY_CAMPAIGN = "https://play.google.com/store/apps/details?id=com.gheymat.app&referrer=utm_source%3Dtelegram-channel%26utm_campaign%3Dchannel"

DESCRIPTION_LIMIT = 255
MESSAGE_LIMIT = 4096

POSTS = [
    "نرخ دلار، طلا، سکه و رمزارز را هر وقت خواستی در «قیمت» ببین. کنار هر نرخ زمان آخرین به‌روزرسانی‌اش هم نوشته شده است.",
    "نمودار دلار و ارزهای اصلی تا سال ۱۳۹۷ عقب می‌رود. بازه را عوض کن و تغییر نرخ را ببین.",
    "تبدیل ارز در «قیمت»: مبلغ را بنویس و معادلش را به تومان یا ریال با آخرین نرخ ببین.",
    "ویجت «قیمت» را روی صفحه اصلی یا صفحه قفل بگذار تا نرخ‌ها را بی‌نیاز از باز کردن اپ ببینی.",
    "«قیمت» روی اپل واچ هم هست: علاقه‌مندی‌هایت و نمودارشان روی مچ دست.",
    "اینترنت قطع شد؟ آخرین نرخ‌هایی که گرفته‌ای در اپ می‌ماند و زمان دریافتشان را هم می‌بینی.",
    "«قیمت» تبلیغ ندارد و برای دیدن نرخ‌ها به حساب کاربری نیاز نیست.",
    "در نسخه پرو می‌توانی در تب «بپرس» درباره دلار، طلا و سکه سؤال کنی و پاسخ کوتاه بگیری.",
    "ارزهایی را که بیشتر دنبال می‌کنی به علاقه‌مندی‌ها اضافه کن تا همیشه دم دستت باشند.",
]

RATING_POST = "اگر «قیمت» به کارت می‌آید، نظرت را در اپ استور بنویس تا دیگران هم پیدایش کنند."
SLOT_BY_WEEKDAY = {0: 0, 2: 1, 5: 2}


def android_live():
    return os.environ.get("TELEGRAM_ANDROID_LIVE", "").strip() == "1"


def links_block():
    lines = ["آیفون، آیپد، مک و اپل واچ:", IOS_CAMPAIGN]
    if android_live():
        lines += ["اندروید:", PLAY_CAMPAIGN]
    return "\n".join(lines)


def description():
    lines = [
        "کانال اپ «قیمت»: نرخ دلار، طلا، سکه و رمزارز، هر نرخ با زمان به‌روزرسانی. بدون تبلیغ.",
        "آیفون: " + IOS_SHORT,
    ]
    if android_live():
        lines.append("اندروید: " + PLAY_SHORT)
    return "\n".join(lines)


def welcome():
    return "\n\n".join([
        "به کانال «قیمت» خوش آمدی.",
        "اینجا خبر اپ، نسخه‌های تازه و ترفندها را می‌گذاریم. نرخ دلار، طلا، سکه و رمزارز را در خود اپ ببین.",
        links_block(),
    ])


def post_index(today):
    slot = SLOT_BY_WEEKDAY.get(today.weekday(), 0)
    return (today.toordinal() // 7 * 3 + slot) % (len(POSTS) + 1)


def scheduled_post(today):
    pool = POSTS + [RATING_POST]
    text = pool[post_index(today)]
    if text == RATING_POST:
        return text + "\n\n" + IOS_REVIEW
    return text + "\n\n" + links_block()


def check_lengths():
    texts = {"description": description(), "welcome": welcome()}
    pool = POSTS + [RATING_POST]
    for i, text in enumerate(pool):
        tail = IOS_REVIEW if text == RATING_POST else links_block()
        texts[f"post{i}"] = text + "\n\n" + tail
    for name, text in texts.items():
        limit = DESCRIPTION_LIMIT if name == "description" else MESSAGE_LIMIT
        if len(text) > limit:
            raise SystemExit(f"{name} is {len(text)} characters, limit {limit}")
    return texts


class TelegramError(Exception):
    pass


def call(method, fields=None, files=None):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
    url = f"https://api.telegram.org/bot{token}/{method}"
    if files:
        boundary = uuid.uuid4().hex
        body = bytearray()
        for key, value in (fields or {}).items():
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode()
        for key, (name, data) in files.items():
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"; filename=\"{name}\"\r\nContent-Type: image/png\r\n\r\n".encode()
            body += data + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        request = urllib.request.Request(url, data=bytes(body), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    else:
        request = urllib.request.Request(url, data=json.dumps(fields or {}).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            payload = json.load(error)
        except ValueError:
            raise TelegramError(f"{method}: HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise TelegramError(f"{method}: network error {type(error).__name__}") from None
    if not payload.get("ok"):
        raise TelegramError(f"{method}: {payload.get('description', 'unknown error')}")
    return payload["result"]


def tolerant(method, fields=None, files=None):
    try:
        return call(method, fields, files)
    except TelegramError as error:
        if "not modified" in str(error).lower():
            print(f"{method}: already up to date")
            return None
        raise


NEEDS = {
    "check": [],
    "description": ["can_change_info"],
    "photo": ["can_change_info"],
    "welcome": ["can_post_messages", "can_edit_messages"],
    "post": ["can_post_messages"],
}


def check_rights(mode):
    me = call("getMe")
    member = call("getChatMember", {"chat_id": CHANNEL, "user_id": me["id"]})
    print(f"bot @{me.get('username')} in {CHANNEL}: {member.get('status')}")
    rights = ["can_post_messages", "can_edit_messages", "can_change_info"]
    for right in rights:
        print(f"  {right}: {bool(member.get(right))}")
    missing = [r for r in NEEDS[mode] if not (member.get("status") == "creator" or member.get(r))]
    if member.get("status") not in ("administrator", "creator") or missing:
        raise SystemExit(f"{mode} needs the bot as an admin with: {', '.join(NEEDS[mode]) or 'admin status'}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "post"
    texts = check_lengths()
    if mode == "dry":
        for name, text in texts.items():
            print(f"--- {name} ({len(text)})\n{text}")
        return
    if mode not in NEEDS:
        raise SystemExit(f"unknown mode {mode}")
    check_rights(mode)
    if mode == "description":
        tolerant("setChatDescription", {"chat_id": CHANNEL, "description": description()})
        print("description set")
    elif mode == "photo":
        with open(ICON, "rb") as handle:
            tolerant("setChatPhoto", {"chat_id": CHANNEL}, {"photo": ("gheymat.png", handle.read())})
        print("photo set")
    elif mode == "welcome":
        message = call("sendMessage", {"chat_id": CHANNEL, "text": welcome(), "disable_notification": True})
        call("pinChatMessage", {"chat_id": CHANNEL, "message_id": message["message_id"], "disable_notification": True})
        print(f"welcome posted and pinned (message {message['message_id']})")
    elif mode == "post":
        message = call("sendMessage", {"chat_id": CHANNEL, "text": scheduled_post(datetime.date.today())})
        print(f"posted message {message['message_id']}")


if __name__ == "__main__":
    main()
