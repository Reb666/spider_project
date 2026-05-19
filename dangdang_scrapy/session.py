import json
import os
import re
from pathlib import Path
from typing import Optional

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "playwright_data"
COOKIE_FILE = Path(__file__).resolve().parent.parent / "data" / "cookies.json"


def _get_data_dir() -> Path:
    env_dir = os.environ.get("DANGDANG_PLAYWRIGHT_DATA_DIR")
    return Path(env_dir) if env_dir else DEFAULT_DATA_DIR


def get_user_data_dir() -> Path:
    return _get_data_dir()


def check_session_url() -> str:
    return os.environ.get("DANGDANG_LOGIN_CHECK_URL", "http://category.dangdang.com/cp01.01.01.00.00.00.html")


LOGIN_POSITIVE = re.compile(r"退出|我的订单|我的当当|我的首页")
LOGIN_NEGATIVE = re.compile(r"请登录|免费注册")


def is_logged_in(html: str) -> bool:
    if not html:
        return False
    has_logout = bool(LOGIN_POSITIVE.search(html))
    no_login_hint = not bool(LOGIN_NEGATIVE.search(html))
    return has_logout and no_login_hint


def save_cookies(cookies: list[dict]) -> None:
    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    COOKIE_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cookies() -> Optional[list[dict]]:
    if not COOKIE_FILE.exists():
        return None
    try:
        return json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def validate_cookies(cookies: list[dict]) -> bool:
    try:
        import urllib.request
        req = urllib.request.Request(check_session_url())
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies if "name" in c and "value" in c)
        if not cookie_str:
            return False
        req.add_header("Cookie", cookie_str)
        resp = urllib.request.urlopen(req, timeout=10)
        html = resp.read().decode(errors="replace")
        return is_logged_in(html)
    except Exception:
        return False
