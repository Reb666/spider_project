import re
from typing import Optional, Tuple

PRICE_RE = re.compile(r"\d+\.?\d*")
INT_RE = re.compile(r"\d+")
RATING_STYLE_RE = re.compile(r"width\s*:\s*([\d.]+)%", re.IGNORECASE)
DETAIL_RATING_RE = re.compile(r'<span class="star"[^>]*style="[^"]*width:\s*([\d.]+)%')
DETAIL_PEOPLE_RE = re.compile(r'id="comm_num_down"[^>]*>(\d+)')
ISBN_RE = re.compile(r"国际标准书号ISBN[：:](\d{13}|\d{10})")


def parse_price(text: object) -> Optional[float]:
    if not text:
        return None
    nums = PRICE_RE.findall(str(text))
    return float(nums[0]) if nums else None


def parse_int(text: object) -> Optional[int]:
    if not text:
        return None
    nums = INT_RE.findall(str(text).replace(",", ""))
    return int(nums[0]) if nums else None


def parse_rating_from_style(style: object) -> Optional[float]:
    if not style:
        return None
    m = RATING_STYLE_RE.search(str(style))
    return float(m.group(1)) if m else None


def parse_review_count(text: object) -> Optional[int]:
    return parse_int(text)


def parse_detail_rating(html: str) -> Tuple[Optional[float], Optional[int]]:
    m = DETAIL_RATING_RE.search(html)
    rating = float(m.group(1)) if m else None
    m = DETAIL_PEOPLE_RE.search(html)
    people = int(m.group(1)) if m else None
    return rating, people


def parse_isbn(html: str) -> Optional[str]:
    m = ISBN_RE.search(html)
    return m.group(1) if m else None
