import os
import scrapy
from dotenv import load_dotenv
from dangdang_scrapy.session import get_user_data_dir

load_dotenv()


class DangdangLoginSpider(scrapy.Spider):
    name = "dangdang_login"
    allowed_domains = ["dangdang.com", "login.dangdang.com"]

    custom_settings = {
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 0,
        "RETRY_TIMES": 0,
        "ITEM_PIPELINES": {},
        "COOKIES_ENABLED": True,
        "PLAYWRIGHT_LAUNCH_OPTIONS": {"headless": False},
    }

    def start_requests(self):
        yield scrapy.Request(
            url="https://login.dangdang.com/",
            callback=self.parse_login,
            meta={
                "playwright": True,
                "playwright_context_kwargs": {
                    "user_data_dir": str(get_user_data_dir()),
                    "headless": False,
                    "viewport": {"width": 1920, "height": 1080},
                },
                "playwright_include_page": True,
            },
            errback=self.on_error,
        )

    async def parse_login(self, response):
        page = response.meta["playwright_page"]

        self.log("╔══════════════════════════════════════════╗", level=20)
        self.log("║  请在浏览器中手动登录当当网              ║", level=20)
        self.log("║  1. 输入手机号，获取短信验证码           ║", level=20)
        self.log("║  2. 输入验证码，完成登录                 ║", level=20)
        self.log("║  登录成功后自动检测并退出               ║", level=20)
        self.log("║  如需放弃请直接 Ctrl+C                   ║", level=20)
        self.log("╚══════════════════════════════════════════╝", level=20)

        from dangdang_scrapy.session import is_logged_in
        for i in range(180):
            try:
                html = await page.content()
                current_url = page.url
                logged_in = is_logged_in(html) or "login.dangdang.com" not in current_url
                if logged_in:
                    self.log(f"登录成功！当前页面: {current_url}", level=20)
                    self.log("浏览器状态已持久化到 data/playwright_data/", level=20)
                    return
            except Exception:
                pass
            if i % 15 == 0 and i > 0:
                self.log(f"等待登录中... ({i * 2}s)", level=20)
            await page.wait_for_timeout(2000)

        self.log("超时（6分钟）未检测到登录状态", level=40)

    def on_error(self, failure):
        self.log(f"请求失败: {failure}", level=40)
        self.log("请确保 DANGDANG_USE_PLAYWRIGHT=true 且 Playwright 已安装", level=40)
