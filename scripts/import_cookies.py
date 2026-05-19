"""导入 Chrome 导出的 Cookie 到 data/cookies.json，供爬虫登录态使用。

用法:
  1. Windows Chrome 打开 dangdang.com，手机号+短信验证码登录
  2. 按 F12 → Console，执行:
       copy(document.cookie)
  3. 粘贴到 data/cookies_raw.txt
  4. 运行 make login (即本脚本)
"""
import os
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

COOKIE_FILE = Path(__file__).resolve().parent.parent / "data" / "cookies.json"
RAW_FILE    = Path(__file__).resolve().parent.parent / "data" / "cookies_raw.txt"

# .gitignore should already include *.json, but be safe
RAW_FILE.parent.mkdir(parents=True, exist_ok=True)


def show_instructions():
    print()
    print("  WSL 无显示器环境：请从 Windows Chrome 导出 Cookie")
    print("  ───────────────────────────────────────────────")
    print("  1. Windows Chrome 打开 https://www.dangdang.com/")
    print("  2. 用手机号 + 短信验证码登录")
    print("  3. 按 F12 → Console，执行:")
    print()
    print("       copy(document.cookie)")
    print()
    print("  4. 粘贴到 data/cookies_raw.txt")
    print("  5. 重新运行 make login")
    print()


def main():
    # 1. Already have cookies.json?
    if COOKIE_FILE.exists():
        from dangdang_scrapy.session import load_cookies, validate_cookies
        cookies = load_cookies()
        if cookies and validate_cookies(cookies):
            print("Cookie 有效，登录态已就绪。")
            return
        else:
            print("Cookie 已过期，重新导入...")
            COOKIE_FILE.unlink(missing_ok=True)

    # 2. Have raw cookie string?
    if not RAW_FILE.exists():
        show_instructions()
        sys.exit(0)

    raw_text = RAW_FILE.read_text(encoding="utf-8").strip()
    if not raw_text:
        show_instructions()
        sys.exit(0)

    # 3. Parse raw cookie string → list of {name, value}
    #    Format: "name1=value1; name2=value2"
    #    Or: JSON array [{name, value}, ...]
    cookies = []
    if raw_text.startswith("["):
        try:
            cookies = json.loads(raw_text)
        except json.JSONDecodeError:
            pass

    if not cookies:
        for part in raw_text.split(";"):
            part = part.strip()
            if "=" in part:
                name, _, value = part.partition("=")
                if name:
                    cookies.append({"name": name, "value": value})

    if not cookies:
        print("无法解析 cookies_raw.txt，请确认格式为: name1=value1; name2=value2")
        sys.exit(1)

    # 4. Validate
    from dangdang_scrapy.session import validate_cookies
    if not validate_cookies(cookies):
        print("Cookie 无效或已过期，请重新登录 dangdang.com 并导出")
        sys.exit(1)

    # 5. Save
    from dangdang_scrapy.session import save_cookies
    save_cookies(cookies)
    print(f"成功导入并验证 {len(cookies)} 条 Cookie → data/cookies.json")
    print("登录态已就绪，现在可以 make crawl / make detail")


if __name__ == "__main__":
    main()
