#!/usr/bin/env python3
"""
🎵 K-pop 포토카드 거래 게시글 통합 수집 스크립트 v2

SerpAPI + Reddit API를 함께 사용하여 더 많은 데이터를 수집합니다.

사용법:
    python collect_kpop_trade_v2.py                      # 세븐틴 기본 수집
    python collect_kpop_trade_v2.py --artist "BTS"       # 다른 아이돌
    python collect_kpop_trade_v2.py --limit 200          # 수집 개수 조정
    python collect_kpop_trade_v2.py --source both        # 두 API 모두 사용 (기본값)
    python collect_kpop_trade_v2.py --source reddit      # Reddit API만 사용
    python collect_kpop_trade_v2.py --source serpapi     # SerpAPI만 사용
"""

import argparse
import json
import os
import time
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import List, Optional

import requests
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

# 환경변수 로드
load_dotenv()


# ============================================================
# 데이터 모델
# ============================================================

class SearchSource(str, Enum):
    """검색 소스"""
    REDDIT = "reddit"
    REDDIT_API = "reddit_api"
    SERPAPI = "serpapi"


class TradePost(BaseModel):
    """거래 게시글 모델"""
    # 기본 정보
    title: str = Field(..., description="제목")
    author: Optional[str] = Field(default=None, description="작성자")
    author_flair: Optional[str] = Field(default=None, description="작성자 플레어")
    
    # 거래 정보 (제목에서 파싱)
    transaction_type: Optional[str] = Field(default=None, description="거래 유형 (WTS/WTB/WTT)")
    country: Optional[str] = Field(default=None, description="국가/지역 코드")
    
    # 게시글 정보
    flair: Optional[str] = Field(default=None, description="게시글 플레어")
    score: int = Field(default=0, description="업보트 수")
    comment_count: int = Field(default=0, description="댓글 수")
    selftext: str = Field(default="", description="본문 내용")
    
    # 시간 정보
    created_timestamp: Optional[datetime] = Field(default=None, description="작성 시간")
    scraped_at: datetime = Field(default_factory=datetime.now, description="수집 시간")
    
    # URL 및 미디어
    permalink: str = Field(..., description="게시글 URL")
    first_image_url: Optional[str] = Field(default=None, description="첫 번째 이미지 URL")
    is_gallery: bool = Field(default=False, description="갤러리 여부")
    
    # 메타 정보
    subreddit: Optional[str] = Field(default=None, description="서브레딧")
    source: str = Field(default="reddit_api", description="수집 소스")


# ============================================================
# Reddit API 클래스
# ============================================================

def parse_title_tags(title: str) -> tuple[Optional[str], Optional[str]]:
    """
    제목에서 거래 유형과 국가 코드 파싱
    예: "[WTS][USA] Seventeen photocard" -> ("WTS", "USA")
    """
    import re
    
    # 거래 유형 패턴
    transaction_types = ["WTS", "WTB", "WTT", "WTT/WTS", "WTS/WTT", "ISO"]
    transaction_type = None
    for tt in transaction_types:
        if tt.lower() in title.lower():
            transaction_type = tt.upper()
            break
    
    # 국가 코드 및 국가명 매핑
    country_mapping = {
        # 코드
        "USA": "USA", "US": "USA", "UK": "UK", "EU": "EU", "WW": "WW",
        "CAN": "CAN", "CA": "CAN", "AUS": "AUS", "AU": "AUS",
        "KR": "KR", "JP": "JP", "SG": "SG", "PH": "PH", "MY": "MY",
        "TH": "TH", "ID": "ID", "VN": "VN", "TW": "TW", "HK": "HK",
        "NZ": "NZ", "DE": "DE", "FR": "FR", "NL": "NL", "IT": "IT",
        "ES": "ES", "BR": "BR", "MX": "MX", "IN": "IN",
        # 전체 국가명
        "CANADA": "CAN", "AUSTRALIA": "AUS", "KOREA": "KR", "JAPAN": "JP",
        "SINGAPORE": "SG", "PHILIPPINES": "PH", "MALAYSIA": "MY",
        "THAILAND": "TH", "INDONESIA": "ID", "VIETNAM": "VN",
        "TAIWAN": "TW", "GERMANY": "DE", "FRANCE": "FR",
        "NETHERLANDS": "NL", "ITALY": "IT", "SPAIN": "ES",
        "BRAZIL": "BR", "MEXICO": "MX", "INDIA": "IN",
    }
    
    # 대괄호 안의 텍스트 추출
    bracket_pattern = r'\[([^\]]+)\]'
    bracket_matches = re.findall(bracket_pattern, title.upper())
    
    country = None
    for match in bracket_matches:
        match_clean = match.strip()
        if match_clean in country_mapping:
            country = country_mapping[match_clean]
            break
    
    return transaction_type, country


class RedditAPIClient:
    """Reddit OAuth API 클라이언트"""

    def __init__(self):
        self.app_id = os.getenv("REDDIT_APP_ID")
        self.secret = os.getenv("REDDIT_SECRET")
        self.user_agent = "kpop-trade-collector/2.0.0 (by /u/kpop_collector)"
        self.access_token = None
        self.token_expires_at = None

    def is_available(self) -> bool:
        """Reddit API 사용 가능 여부"""
        return bool(self.app_id and self.secret)

    def authenticate(self) -> bool:
        """Reddit OAuth 인증"""
        if not self.is_available():
            return False

        # 토큰이 아직 유효하면 재사용
        if self.access_token and self.token_expires_at:
            if datetime.now() < self.token_expires_at:
                return True

        try:
            auth = requests.auth.HTTPBasicAuth(self.app_id, self.secret)
            data = {
                "grant_type": "client_credentials",
                "device_id": "kpop_trade_collector_v2",
            }
            headers = {"User-Agent": self.user_agent}

            response = requests.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=auth,
                data=data,
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()

            token_data = response.json()
            self.access_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)
            self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 60)

            return True

        except Exception as e:
            print(f"  ⚠️ Reddit 인증 실패: {e}")
            return False

    @retry(
        retry=retry_if_exception_type((requests.exceptions.RequestException, TimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def search_subreddit(
        self,
        subreddit: str,
        query: str,
        limit: int = 100,
        sort: str = "relevance",
        time_filter: str = "year",
    ) -> List[TradePost]:
        """서브레딧에서 검색"""
        if not self.access_token:
            if not self.authenticate():
                return []

        headers = {
            "Authorization": f"bearer {self.access_token}",
            "User-Agent": self.user_agent,
        }

        params = {
            "q": query,
            "limit": min(limit, 100),
            "sort": sort,
            "t": time_filter,
            "restrict_sr": True,
        }

        url = f"https://oauth.reddit.com/r/{subreddit}/search"

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"    ⚠️ 검색 실패 r/{subreddit}: {e}")
            return []

        posts = []
        six_months_ago = datetime.now() - timedelta(days=180)

        for post in data.get("data", {}).get("children", []):
            post_data = post.get("data", {})
            created_at = datetime.fromtimestamp(post_data.get("created_utc", 0))

            # 6개월 이내 게시글만
            if created_at < six_months_ago:
                continue

            title = post_data.get("title", "")
            transaction_type, country = parse_title_tags(title)
            
            # 이미지 URL 추출
            first_image_url = None
            is_gallery = post_data.get("is_gallery", False)
            
            if is_gallery and "gallery_data" in post_data:
                # 갤러리인 경우
                media_metadata = post_data.get("media_metadata", {})
                if media_metadata:
                    first_key = list(media_metadata.keys())[0]
                    first_image_url = media_metadata[first_key].get("s", {}).get("u", "")
            elif post_data.get("url", "").endswith((".jpg", ".png", ".gif", ".jpeg", ".webp")):
                first_image_url = post_data.get("url")
            elif "preview" in post_data:
                images = post_data.get("preview", {}).get("images", [])
                if images:
                    first_image_url = images[0].get("source", {}).get("url", "")
            
            trade_post = TradePost(
                title=title,
                author=post_data.get("author"),
                author_flair=post_data.get("author_flair_text"),
                transaction_type=transaction_type,
                country=country,
                flair=post_data.get("link_flair_text"),
                score=post_data.get("score", 0),
                comment_count=post_data.get("num_comments", 0),
                selftext=post_data.get("selftext", ""),
                created_timestamp=created_at,
                permalink=f"https://reddit.com{post_data.get('permalink', '')}",
                first_image_url=first_image_url,
                is_gallery=is_gallery,
                subreddit=subreddit,
                source="reddit_api",
            )
            posts.append(trade_post)

        return posts

    def get_new_posts(self, subreddit: str, limit: int = 100) -> List[TradePost]:
        """서브레딧 최신 게시글 가져오기 (단일 페이지)"""
        posts, _ = self.get_posts_paginated(subreddit, limit=limit, max_pages=1)
        return posts

    def get_posts_paginated(
        self,
        subreddit: str,
        limit: int = 500,
        max_pages: int = 10,
        min_date: Optional[datetime] = None,
    ) -> tuple[List[TradePost], Optional[str]]:
        """
        서브레딧 게시글 페이지네이션으로 가져오기
        
        Args:
            subreddit: 서브레딧 이름
            limit: 총 가져올 게시글 수
            max_pages: 최대 페이지 수 (각 페이지 100개)
            min_date: 이 날짜 이후 게시글만 (None이면 제한 없음)
        
        Returns:
            (게시글 리스트, 마지막 after 토큰)
        """
        if not self.access_token:
            if not self.authenticate():
                return [], None

        headers = {
            "Authorization": f"bearer {self.access_token}",
            "User-Agent": self.user_agent,
        }

        all_posts = []
        after = None
        page = 0

        while len(all_posts) < limit and page < max_pages:
            params = {"limit": 100}
            if after:
                params["after"] = after

            url = f"https://oauth.reddit.com/r/{subreddit}/new"

            try:
                response = requests.get(url, headers=headers, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                print(f"      ⚠️ 페이지 {page + 1} 실패: {e}")
                break

            children = data.get("data", {}).get("children", [])
            if not children:
                break

            stop_pagination = False
            for post in children:
                post_data = post.get("data", {})
                created_at = datetime.fromtimestamp(post_data.get("created_utc", 0))

                # 날짜 필터 확인
                if min_date and created_at < min_date:
                    stop_pagination = True
                    break

                title = post_data.get("title", "")
                transaction_type, country = parse_title_tags(title)
                
                # 이미지 URL 추출
                first_image_url = None
                is_gallery = post_data.get("is_gallery", False)
                
                if is_gallery and "gallery_data" in post_data:
                    media_metadata = post_data.get("media_metadata", {})
                    if media_metadata:
                        first_key = list(media_metadata.keys())[0]
                        first_image_url = media_metadata[first_key].get("s", {}).get("u", "")
                elif post_data.get("url", "").endswith((".jpg", ".png", ".gif", ".jpeg", ".webp")):
                    first_image_url = post_data.get("url")
                elif "preview" in post_data:
                    images = post_data.get("preview", {}).get("images", [])
                    if images:
                        first_image_url = images[0].get("source", {}).get("url", "")
                
                trade_post = TradePost(
                    title=title,
                    author=post_data.get("author"),
                    author_flair=post_data.get("author_flair_text"),
                    transaction_type=transaction_type,
                    country=country,
                    flair=post_data.get("link_flair_text"),
                    score=post_data.get("score", 0),
                    comment_count=post_data.get("num_comments", 0),
                    selftext=post_data.get("selftext", ""),
                    created_timestamp=created_at,
                    permalink=f"https://reddit.com{post_data.get('permalink', '')}",
                    first_image_url=first_image_url,
                    is_gallery=is_gallery,
                    subreddit=subreddit,
                    source="reddit_api",
                )
                all_posts.append(trade_post)

                if len(all_posts) >= limit:
                    break

            if stop_pagination:
                break

            after = data.get("data", {}).get("after")
            if not after:
                break

            page += 1
            time.sleep(1)  # Rate limit

        return all_posts, after


# ============================================================
# SerpAPI 클래스
# ============================================================

class SerpAPIClient:
    """SerpAPI 클라이언트"""

    def __init__(self):
        self.api_key = os.getenv("SERPAPI_KEY")
        self.base_url = "https://serpapi.com/search"

    def is_available(self) -> bool:
        """SerpAPI 사용 가능 여부"""
        return bool(self.api_key)

    @retry(
        retry=retry_if_exception_type((requests.exceptions.RequestException, TimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def search(
        self,
        query: str,
        language: str = "en",
        max_results: int = 10,
    ) -> List[TradePost]:
        """Google 검색 (Reddit 사이트 필터)"""
        if not self.is_available():
            return []

        params = {
            "q": f"{query} site:reddit.com",
            "api_key": self.api_key,
            "num": min(max_results, 100),
            "hl": language,
            "gl": "kr" if language == "ko" else "us",
            "tbs": "qdr:m6",  # 최근 6개월
        }

        try:
            response = requests.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                print(f"    ⚠️ SerpAPI 오류: {data.get('error')}")
                return []

        except Exception as e:
            print(f"    ⚠️ SerpAPI 검색 실패: {e}")
            return []

        posts = []
        for item in data.get("organic_results", []):
            title = item.get("title", "")
            transaction_type, country = parse_title_tags(title)
            
            post = TradePost(
                title=title,
                author=None,
                author_flair=None,
                transaction_type=transaction_type,
                country=country,
                flair=None,
                score=0,
                comment_count=0,
                selftext=item.get("snippet", ""),
                created_timestamp=None,
                permalink=item.get("link", ""),
                first_image_url=None,
                is_gallery=False,
                subreddit=None,
                source="serpapi",
            )
            posts.append(post)

        return posts


# ============================================================
# 통합 수집기
# ============================================================

class KpopTradeCollector:
    """K-pop 포토카드 거래 게시글 통합 수집기"""

    # K-pop 거래 관련 서브레딧
    SUBREDDITS = [
        "kpopforsale",
        "kpopcollections",
        "kpoptrade",
        "adultkpopfans",
    ]

    # 거래 키워드
    TRADE_KEYWORDS = [
        "wts", "wtb", "wtt", "trade", "trading", "selling", "buying",
        "for sale", "iso", "양도", "판매", "구해", "삽니다", "팝니다", "교환"
    ]

    def __init__(self):
        self.reddit = RedditAPIClient()
        self.serpapi = SerpAPIClient()

    def get_search_queries(self, artist: str) -> dict:
        """아티스트별 검색 쿼리 생성"""
        return {
            "reddit_api": [
                f"{artist} photocard",
                f"{artist} pc",
                f"{artist} WTS",
                f"{artist} WTB",
                f"{artist} WTT",
                f"{artist} trade",
                f"{artist} selling",
            ],
            "serpapi": [
                f"WTS {artist} photocard",
                f"WTB {artist} photocard",
                f"WTT {artist} photocard",
                f"{artist} 포토카드 양도",
                f"kpopforsale {artist}",
            ],
        }

    def is_trade_post(self, post: TradePost) -> bool:
        """거래 관련 게시글인지 확인"""
        # transaction_type이 이미 파싱되어 있으면 거래글
        if post.transaction_type:
            return True
        combined = (post.title + " " + post.selftext).lower()
        return any(kw in combined for kw in self.TRADE_KEYWORDS)

    def contains_artist(self, post: TradePost, artist: str) -> bool:
        """아티스트 관련 게시글인지 확인"""
        artist_lower = artist.lower()
        # 아티스트 이름 변형 (예: Seventeen -> svt, 세븐틴)
        artist_variants = [artist_lower]
        
        # 주요 아티스트 별명 매핑
        artist_aliases = {
            "seventeen": ["svt", "세븐틴", "sebong"],
            "bts": ["방탄소년단", "bangtan"],
            "twice": ["트와이스"],
            "blackpink": ["블랙핑크", "블핑"],
            "stray kids": ["skz", "스트레이키즈", "스키즈"],
            "newjeans": ["뉴진스", "nj"],
            "aespa": ["에스파"],
            "nct": ["엔시티"],
            "exo": ["엑소"],
            "red velvet": ["레드벨벳", "레벨"],
            "itzy": ["있지"],
            "txt": ["투모로우바이투게더", "tomorrow x together"],
            "enhypen": ["엔하이픈"],
            "ive": ["아이브"],
            "le sserafim": ["르세라핌"],
        }
        
        # 별명 추가
        if artist_lower in artist_aliases:
            artist_variants.extend(artist_aliases[artist_lower])
        
        combined = (post.title + " " + post.selftext).lower()
        return any(variant in combined for variant in artist_variants)

    def collect_from_reddit_api(
        self,
        artist: Optional[str] = None,
        limit: int = 200,
        max_pages: int = 5,
        months: int = 12,
    ) -> List[TradePost]:
        """
        Reddit API로 수집
        
        Args:
            artist: 아티스트 이름 (None이면 모든 거래글)
            limit: 서브레딧당 수집할 게시글 수
            max_pages: 서브레딧당 최대 페이지 수
            months: 몇 개월 전까지 수집할지
        """
        if not self.reddit.is_available():
            print("  ⚠️ Reddit API 키가 설정되지 않았습니다.")
            return []

        if not self.reddit.authenticate():
            return []

        print("  ✅ Reddit API 인증 성공")
        
        min_date = datetime.now() - timedelta(days=months * 30)
        print(f"  📅 수집 범위: {min_date.strftime('%Y-%m-%d')} ~ 현재 ({months}개월)")

        all_posts = []

        # 각 서브레딧에서 페이지네이션으로 수집
        for subreddit in self.SUBREDDITS:
            print(f"\n  📍 r/{subreddit} (최대 {max_pages}페이지)")

            posts, last_after = self.reddit.get_posts_paginated(
                subreddit,
                limit=limit,
                max_pages=max_pages,
                min_date=min_date,
            )
            all_posts.extend(posts)
            
            oldest = min([p.created_timestamp for p in posts if p.created_timestamp], default=None) if posts else None
            oldest_str = oldest.strftime('%Y-%m-%d') if oldest else "N/A"
            print(f"    ✅ {len(posts)} posts (oldest: {oldest_str})")
            
            time.sleep(1)  # Rate limit

        # 추가로 키워드 검색 (artist가 지정된 경우)
        if artist:
            queries = self.get_search_queries(artist)["reddit_api"]
            for subreddit in self.SUBREDDITS[:2]:  # 주요 2개만
                for query in queries[:2]:
                    print(f"    [search] '{query}'...")
                    search_posts = self.reddit.search_subreddit(subreddit, query, limit=50)
                    all_posts.extend(search_posts)
                    print(f"    ✅ {len(search_posts)} posts")
                    time.sleep(1)

        return all_posts

    def collect_from_serpapi(self, artist: str, limit: int = 100) -> List[TradePost]:
        """SerpAPI로 수집"""
        if not self.serpapi.is_available():
            print("  ⚠️ SERPAPI_KEY가 설정되지 않았습니다.")
            return []

        print("  ✅ SerpAPI 사용 가능")

        queries = self.get_search_queries(artist)["serpapi"]
        all_posts = []

        for query in queries:
            print(f"    [search] '{query}'...")
            posts = self.serpapi.search(query, language="en", max_results=10)
            all_posts.extend(posts)
            print(f"    ✅ {len(posts)} posts")

        return all_posts

    def collect(
        self,
        artist: Optional[str] = None,
        limit: int = 500,
        source: str = "both",
        max_pages: int = 10,
        months: int = 12,
    ) -> List[TradePost]:
        """
        통합 수집 실행
        
        Args:
            artist: 아티스트 이름 (None이면 모든 거래글)
            limit: 최대 수집 개수
            source: 데이터 소스 (both, reddit, serpapi)
            max_pages: 서브레딧당 최대 페이지 수
            months: 몇 개월 전까지 수집
        """
        print("=" * 60)
        if artist:
            print(f"🎵 {artist} 포토카드 거래 게시글 통합 수집 v2")
        else:
            print("🎵 K-pop 전체 포토카드 거래 게시글 수집 v2")
        print("=" * 60)
        print(f"🎯 Target: WTS/WTB/WTT 거래 게시글")
        print(f"📊 Limit: ~{limit} posts")
        print(f"📅 Range: 최근 {months}개월")
        print(f"📄 Pages: 서브레딧당 최대 {max_pages}페이지")
        print(f"🔧 Source: {source}")
        print()

        all_posts = []

        # Reddit API 수집
        if source in ["both", "reddit"]:
            print("📡 [1/2] Reddit API 수집 중...")
            reddit_posts = self.collect_from_reddit_api(
                artist=artist,
                limit=limit,
                max_pages=max_pages,
                months=months,
            )
            all_posts.extend(reddit_posts)
            print(f"\n  📊 Reddit API 결과: {len(reddit_posts)}개")

        # SerpAPI 수집 (artist가 지정된 경우만)
        if source in ["both", "serpapi"] and artist:
            print("\n🔍 [2/2] SerpAPI 수집 중...")
            serp_posts = self.collect_from_serpapi(artist, limit)
            all_posts.extend(serp_posts)
            print(f"\n  📊 SerpAPI 결과: {len(serp_posts)}개")
        elif source in ["both", "serpapi"] and not artist:
            print("\n🔍 [2/2] SerpAPI 건너뜀 (아티스트 미지정 시 비효율적)")

        # 중복 제거
        seen_urls = set()
        unique_posts = []
        for post in all_posts:
            normalized_url = post.permalink.rstrip("/")
            if normalized_url not in seen_urls:
                unique_posts.append(post)
                seen_urls.add(normalized_url)

        print(f"\n📊 중복 제거 후: {len(unique_posts)}개")

        # 아티스트 필터링 (지정된 경우만)
        if artist:
            artist_posts = [p for p in unique_posts if self.contains_artist(p, artist)]
            print(f"🎤 아티스트 '{artist}' 필터 후: {len(artist_posts)}개")
        else:
            artist_posts = unique_posts
            print("🎤 아티스트 필터: 없음 (전체 수집)")

        # 거래 키워드 필터링
        trade_posts = [p for p in artist_posts if self.is_trade_post(p)]
        print(f"🔍 거래 키워드 필터 후: {len(trade_posts)}개")

        # 날짜순 정렬 (최신순)
        trade_posts.sort(key=lambda p: p.created_timestamp or datetime.min, reverse=True)

        # 제한 적용
        if len(trade_posts) > limit:
            trade_posts = trade_posts[:limit]

        return trade_posts

    def save_to_jsonl(self, posts: List[TradePost], artist: Optional[str] = None) -> Path:
        """JSONL 파일로 저장"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        if artist:
            artist_safe = artist.lower().replace(" ", "_")
            filename = Path("data") / f"{artist_safe}_trade_v2_{timestamp}.jsonl"
        else:
            filename = Path("data") / f"kpop_all_trade_{timestamp}.jsonl"
        Path("data").mkdir(exist_ok=True)

        with open(filename, "w", encoding="utf-8") as f:
            for post in posts:
                data = {
                    "title": post.title,
                    "author": post.author,
                    "author_flair": post.author_flair,
                    "transaction_type": post.transaction_type,
                    "country": post.country,
                    "flair": post.flair,
                    "score": post.score,
                    "comment_count": post.comment_count,
                    "selftext": post.selftext,
                    "created_timestamp": post.created_timestamp.isoformat() if post.created_timestamp else None,
                    "permalink": post.permalink,
                    "first_image_url": post.first_image_url,
                    "is_gallery": post.is_gallery,
                    "scraped_at": post.scraped_at.isoformat(),
                }
                f.write(json.dumps(data, ensure_ascii=False) + "\n")

        return filename


# ============================================================
# 메인 실행
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="K-pop 포토카드 거래 게시글 통합 수집 v2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 전체 K-pop 거래 게시글 수집 (아티스트 필터 없음)
  python collect_kpop_trade_v2.py --all
  
  # 전체 수집 + 더 많은 데이터 (10페이지, 12개월)
  python collect_kpop_trade_v2.py --all --pages 10 --months 12
  
  # 특정 아티스트만 수집
  python collect_kpop_trade_v2.py --artist "Seventeen"
  python collect_kpop_trade_v2.py --artist "BTS"
  
  # 대량 수집 (1000개, 20페이지, 24개월)
  python collect_kpop_trade_v2.py --all --limit 1000 --pages 20 --months 24
        """
    )

    parser.add_argument(
        "--artist",
        type=str,
        default=None,
        help="아티스트 이름 (미지정 시 --all 필요)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="모든 K-pop 거래 게시글 수집 (아티스트 필터 없음)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="최대 수집 개수 (기본: 500)",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=5,
        help="서브레딧당 최대 페이지 수 (기본: 5, 페이지당 100개)",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=6,
        help="몇 개월 전까지 수집 (기본: 6)",
    )
    parser.add_argument(
        "--source",
        type=str,
        choices=["both", "reddit", "serpapi"],
        default="reddit",
        help="데이터 소스 (기본: reddit)",
    )

    args = parser.parse_args()

    # --all 또는 --artist 중 하나는 필수
    if not args.all and not args.artist:
        print("❌ --all 또는 --artist 중 하나를 지정해주세요.")
        print("예시:")
        print("  python collect_kpop_trade_v2.py --all")
        print("  python collect_kpop_trade_v2.py --artist 'Seventeen'")
        return

    artist = None if args.all else args.artist

    # 수집 실행
    collector = KpopTradeCollector()
    posts = collector.collect(
        artist=artist,
        limit=args.limit,
        source=args.source,
        max_pages=args.pages,
        months=args.months,
    )

    if not posts:
        print("\n❌ 수집된 게시글이 없습니다.")
        print("💡 API 키 설정을 확인하세요:")
        print("   - REDDIT_APP_ID, REDDIT_SECRET (.env)")
        print("   - SERPAPI_KEY (.env)")
        return

    # 저장
    filename = collector.save_to_jsonl(posts, artist)

    print(f"\n{'=' * 60}")
    print(f"✅ 수집 완료: {len(posts)}개 거래 게시글")
    print(f"💾 저장: {filename}")
    print("=" * 60)

    # 소스별 통계
    sources = {}
    for post in posts:
        sources[post.source] = sources.get(post.source, 0) + 1

    print("\n📊 소스별 통계:")
    for source, count in sorted(sources.items(), key=lambda x: -x[1]):
        print(f"  - {source}: {count}개")

    # 샘플 출력
    print("\n📋 수집된 거래 게시글 샘플:")
    for i, post in enumerate(posts[:10], 1):
        title = post.title[:50] + "..." if len(post.title) > 50 else post.title
        source_tag = f"[{post.source}]"
        print(f"  {i}. {source_tag} {title}")

    if len(posts) > 10:
        print(f"  ... 외 {len(posts) - 10}개")


if __name__ == "__main__":
    main()

