import os
import random
import logging
from scrapy.downloadermiddlewares.useragent import UserAgentMiddleware
from dangdang_scrapy.session import load_cookies, save_cookies, check_session_url

logger = logging.getLogger(__name__)


class RandomUserAgentMiddleware(UserAgentMiddleware):
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    ]

    def process_request(self, request, spider):
        request.headers["User-Agent"] = random.choice(self.user_agents)


class SessionMiddleware:
    def __init__(self):
        self._cookies = None

    def open_spider(self, spider):
        if getattr(spider, "name", "") in ("dangdang_login",):
            return
        self._cookies = load_cookies()

    def process_request(self, request, spider):
        if getattr(spider, "name", "") in ("dangdang_login",):
            return
        if self._cookies:
            request.cookies = self._cookies

    def process_response(self, request, response, spider):
        if getattr(spider, "name", "") in ("dangdang_login",):
            return response
        login_check_url = check_session_url()
        if response.url.rstrip("/") == login_check_url.rstrip("/"):
            from dangdang_scrapy.session import is_logged_in
            if not is_logged_in(response.text):
                logger.warning("Session 可能已失效，请重新运行 make login")
                self._cookies = None
        return response
