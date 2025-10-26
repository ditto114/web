"""MapleStory Worlds 친구 코드로 PPSN을 찾는 도구.

이 스크립트는 지정된 친구 코드(5글자)에 해당하는 MapleStory Worlds 프로필의
PPSN을 친구 목록 페이지를 크롤링하여 찾아냅니다.

사용 예시:
    python maple_ppsn_finder.py kJimR

스크립트는 다음 순서로 동작합니다.
1. 대상 친구 코드의 프로필 페이지에서 노출된 친구 목록을 수집합니다.
2. 각 친구의 "전체 친구 목록" 페이지를 페이지네이션하며 탐색합니다.
3. 목록에서 대상 친구 코드를 발견하면 해당 항목의 PPSN을 출력합니다.

Windows 환경에서 동작하도록 작성되었으며, 표준 라이브러리만 사용합니다.
네트워크 환경에 따라 MapleStory Worlds 서버 접근이 제한될 수 있으므로 주의하세요.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from html.parser import HTMLParser
from typing import Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "https://maplestoryworlds.nexon.com"
PROFILE_URL = BASE_URL + "/ko/profile/{code}"
FRIENDS_PAGE_URL = BASE_URL + "/profile/{code}/friends?type=friends&page={page}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0 Safari/537.36"
)
FRIEND_CODE_PATTERN = re.compile(r"^/profile/([A-Za-z0-9]{5})$")


class FriendListParser(HTMLParser):
    """HTML 파서를 이용해 친구 목록에서 (친구코드, PPSN) 쌍을 추출합니다."""

    def __init__(self) -> None:
        super().__init__()
        self._within_friend_section = False
        self._current_ppsn: Optional[str] = None
        self.entries: List[Tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attrs_dict = {key: value for key, value in attrs if value is not None}

        if tag == "section":
            class_name = attrs_dict.get("class", "")
            if "section_friend" in class_name:
                self._within_friend_section = True

        if not self._within_friend_section:
            return

        if "ppsn" in attrs_dict:
            self._current_ppsn = attrs_dict["ppsn"]

        if tag == "a" and "href" in attrs_dict:
            match = FRIEND_CODE_PATTERN.match(attrs_dict["href"])
            if match:
                code = match.group(1)
                ppsn = attrs_dict.get("ppsn", self._current_ppsn)
                if ppsn:
                    self.entries.append((code, ppsn))

    def handle_endtag(self, tag: str) -> None:
        if tag == "section" and self._within_friend_section:
            self._within_friend_section = False
            self._current_ppsn = None
        elif tag == "li":
            self._current_ppsn = None


def fetch(url: str) -> str:
    """지정된 URL의 HTML을 반환합니다."""

    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, "ignore")


def extract_friend_codes_from_profile(html: str) -> List[str]:
    """프로필 페이지에서 노출된 친구 코드들을 추출합니다."""

    parser = FriendListParser()
    parser.feed(html)
    return [code for code, _ in parser.entries]


def extract_entries_from_friends_page(html: str) -> List[Tuple[str, str]]:
    parser = FriendListParser()
    parser.feed(html)
    return parser.entries


def get_initial_friends(target_code: str) -> List[str]:
    profile_url = PROFILE_URL.format(code=target_code)
    html = fetch(profile_url)
    codes = extract_friend_codes_from_profile(html)
    if not codes:
        raise RuntimeError(
            "프로필 페이지에서 친구 목록을 찾지 못했습니다. "
            "친구 코드가 올바른지 확인하세요."
        )
    return codes


def iter_friend_pages(friend_code: str, *, delay: float = 0.5) -> Iterable[List[Tuple[str, str]]]:
    page = 1
    seen_empty = 0
    while True:
        url = FRIENDS_PAGE_URL.format(code=friend_code, page=page)
        try:
            html = fetch(url)
        except HTTPError as exc:
            if exc.code == 404:
                break
            raise
        entries = extract_entries_from_friends_page(html)
        if not entries:
            seen_empty += 1
            if seen_empty >= 2:
                break
        else:
            seen_empty = 0
            yield entries
        page += 1
        if delay:
            time.sleep(delay)


def find_ppsn(target_code: str, *, delay: float = 0.5) -> Optional[Tuple[str, str]]:
    target_code_upper = target_code.upper()
    friends = get_initial_friends(target_code)

    for friend_code in friends:
        print(f"[정보] 친구 {friend_code} 의 목록을 탐색합니다...")
        try:
            for entries in iter_friend_pages(friend_code, delay=delay):
                for code, ppsn in entries:
                    if code.upper() == target_code_upper:
                        return ppsn, friend_code
        except URLError as exc:
            print(f"[경고] {friend_code} 의 친구 목록을 불러오지 못했습니다: {exc}")
        except HTTPError as exc:
            print(f"[경고] {friend_code} 의 친구 목록 요청 실패({exc.code}): {exc.reason}")

    return None


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MapleStory Worlds PPSN 조회기")
    parser.add_argument(
        "code",
        help="PPSN을 찾고자 하는 친구 코드 (5글자)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="페이지 요청 사이에 둘 대기 시간 (초). 기본값은 0.5초",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    code = args.code.strip()

    if not re.fullmatch(r"[A-Za-z0-9]{5}", code):
        print("[오류] 친구 코드는 영문 대소문자/숫자의 5글자여야 합니다.")
        return 1

    try:
        result = find_ppsn(code, delay=args.delay)
    except HTTPError as exc:
        print(f"[오류] 프로필 페이지 요청 실패({exc.code}): {exc.reason}")
        return 1
    except URLError as exc:
        print(f"[오류] 네트워크 오류가 발생했습니다: {exc}")
        return 1
    except RuntimeError as exc:
        print(f"[오류] {exc}")
        return 1

    if result is None:
        print("[결과] 친구 목록 어디에서도 해당 친구 코드를 찾지 못했습니다.")
        return 2

    ppsn, via_friend = result
    print(
        f"[결과] 친구 코드 {code} 의 PPSN은 {ppsn} 입니다. "
        f"(친구 {via_friend} 의 목록에서 확인)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
