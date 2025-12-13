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
    url: str = Field(..., description="게시글 URL")
    title: str = Field(..., description="제목")
    content: str = Field(default="", description="본문 내용")
    snippet: str = Field(default="", description="내용 미리보기")
    author: Optional[str] = Field(default=None, description="작성자")
    subreddit: Optional[str] = Field(default=None, description="서브레딧")
    source: str = Field(..., description="수집 소스")
    lang: str = Field(default="en", description="언어 코드")
    created_at: Optional[datetime] = Field(default=None, description="작성 시간")
    score: int = Field(default=0, description="업보트 수")
    num_comments: int = Field(default=0, description="댓글 수")
    queried_at: datetime = Field(default_factory=datetime.now, description="수집 시간")


# ============================================================
# Reddit API 클래스
# ============================================================

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

            trade_post = TradePost(
                url=f"https://reddit.com{post_data.get('permalink', '')}",
                title=post_data.get("title", ""),
                content=post_data.get("selftext", "")[:500],  # 본문 500자 제한
                snippet=post_data.get("selftext", "")[:200],
                author=post_data.get("author"),
                subreddit=subreddit,
                source="reddit_api",
                lang="en",
                created_at=created_at,
                score=post_data.get("score", 0),
                num_comments=post_data.get("num_comments", 0),
            )
            posts.append(trade_post)

        return posts

    def get_new_posts(self, subreddit: str, limit: int = 100) -> List[TradePost]:
        """서브레딧 최신 게시글 가져오기"""
        if not self.access_token:
            if not self.authenticate():
                return []

        headers = {
            "Authorization": f"bearer {self.access_token}",
            "User-Agent": self.user_agent,
        }

        params = {"limit": min(limit, 100)}
        url = f"https://oauth.reddit.com/r/{subreddit}/new"

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"    ⚠️ 최신 게시글 가져오기 실패: {e}")
            return []

        posts = []
        for post in data.get("data", {}).get("children", []):
            post_data = post.get("data", {})
            created_at = datetime.fromtimestamp(post_data.get("created_utc", 0))

            trade_post = TradePost(
                url=f"https://reddit.com{post_data.get('permalink', '')}",
                title=post_data.get("title", ""),
                content=post_data.get("selftext", "")[:500],
                snippet=post_data.get("selftext", "")[:200],
                author=post_data.get("author"),
                subreddit=subreddit,
                source="reddit_api",
                lang="en",
                created_at=created_at,
                score=post_data.get("score", 0),
                num_comments=post_data.get("num_comments", 0),
            )
            posts.append(trade_post)

        return posts


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
            post = TradePost(
                url=item.get("link", ""),
                title=item.get("title", ""),
                snippet=item.get("snippet", ""),
                source="serpapi",
                lang=language,
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
        combined = (post.title + " " + post.snippet + " " + post.content).lower()
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
        
        combined = (post.title + " " + post.snippet + " " + post.content).lower()
        return any(variant in combined for variant in artist_variants)

    def collect_from_reddit_api(self, artist: str, limit: int = 200) -> List[TradePost]:
        """Reddit API로 수집"""
        if not self.reddit.is_available():
            print("  ⚠️ Reddit API 키가 설정되지 않았습니다.")
            return []

        if not self.reddit.authenticate():
            return []

        print("  ✅ Reddit API 인증 성공")

        queries = self.get_search_queries(artist)["reddit_api"]
        all_posts = []

        # 각 서브레딧에서 검색
        for subreddit in self.SUBREDDITS:
            print(f"\n  📍 r/{subreddit}")

            # 최신 게시글 가져오기
            print(f"    [new] 최신 게시글...")
            new_posts = self.reddit.get_new_posts(subreddit, limit=50)
            all_posts.extend(new_posts)
            print(f"    ✅ {len(new_posts)} posts")
            time.sleep(1)  # Rate limit

            # 키워드 검색
            for query in queries[:3]:  # 상위 3개 쿼리만
                print(f"    [search] '{query}'...")
                search_posts = self.reddit.search_subreddit(subreddit, query, limit=25)
                all_posts.extend(search_posts)
                print(f"    ✅ {len(search_posts)} posts")
                time.sleep(1)  # Rate limit

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
        artist: str = "Seventeen",
        limit: int = 200,
        source: str = "both",
    ) -> List[TradePost]:
        """통합 수집 실행"""
        print("=" * 60)
        print(f"🎵 {artist} 포토카드 거래 게시글 통합 수집 v2")
        print("=" * 60)
        print(f"🎯 Target: WTS/WTB/WTT 거래 게시글")
        print(f"📊 Limit: ~{limit} posts")
        print(f"🔧 Source: {source}")
        print()

        all_posts = []

        # Reddit API 수집
        if source in ["both", "reddit"]:
            print("📡 [1/2] Reddit API 수집 중...")
            reddit_posts = self.collect_from_reddit_api(artist, limit)
            all_posts.extend(reddit_posts)
            print(f"\n  📊 Reddit API 결과: {len(reddit_posts)}개")

        # SerpAPI 수집
        if source in ["both", "serpapi"]:
            print("\n🔍 [2/2] SerpAPI 수집 중...")
            serp_posts = self.collect_from_serpapi(artist, limit)
            all_posts.extend(serp_posts)
            print(f"\n  📊 SerpAPI 결과: {len(serp_posts)}개")

        # 중복 제거
        seen_urls = set()
        unique_posts = []
        for post in all_posts:
            # URL 정규화 (trailing slash 제거)
            normalized_url = post.url.rstrip("/")
            if normalized_url not in seen_urls:
                unique_posts.append(post)
                seen_urls.add(normalized_url)

        print(f"\n📊 중복 제거 후: {len(unique_posts)}개")

        # 아티스트 필터링
        artist_posts = [p for p in unique_posts if self.contains_artist(p, artist)]
        print(f"🎤 아티스트 '{artist}' 필터 후: {len(artist_posts)}개")

        # 거래 키워드 필터링
        trade_posts = [p for p in artist_posts if self.is_trade_post(p)]
        print(f"🔍 거래 키워드 필터 후: {len(trade_posts)}개")

        # 제한 적용
        if len(trade_posts) > limit:
            trade_posts = trade_posts[:limit]

        return trade_posts

    def save_to_jsonl(self, posts: List[TradePost], artist: str) -> Path:
        """JSONL 파일로 저장"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        artist_safe = artist.lower().replace(" ", "_")
        filename = Path("data") / f"{artist_safe}_trade_v2_{timestamp}.jsonl"
        Path("data").mkdir(exist_ok=True)

        with open(filename, "w", encoding="utf-8") as f:
            for post in posts:
                data = {
                    "url": post.url,
                    "title": post.title,
                    "content": post.content,
                    "snippet": post.snippet,
                    "author": post.author,
                    "subreddit": post.subreddit,
                    "source": post.source,
                    "lang": post.lang,
                    "created_at": post.created_at.isoformat() if post.created_at else None,
                    "score": post.score,
                    "num_comments": post.num_comments,
                    "queried_at": post.queried_at.isoformat(),
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
  python collect_kpop_trade_v2.py                       # 세븐틴 수집
  python collect_kpop_trade_v2.py --artist "BTS"        # BTS 수집
  python collect_kpop_trade_v2.py --artist "TWICE"      # 트와이스 수집
  python collect_kpop_trade_v2.py --limit 300           # 300개까지 수집
  python collect_kpop_trade_v2.py --source reddit       # Reddit API만 사용
  python collect_kpop_trade_v2.py --source serpapi      # SerpAPI만 사용
  python collect_kpop_trade_v2.py --source both         # 둘 다 사용 (기본값)
        """
    )

    parser.add_argument(
        "--artist",
        type=str,
        default="Seventeen",
        help="아티스트 이름 (기본: Seventeen)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="최대 수집 개수 (기본: 200)",
    )
    parser.add_argument(
        "--source",
        type=str,
        choices=["both", "reddit", "serpapi"],
        default="both",
        help="데이터 소스 (기본: both)",
    )

    args = parser.parse_args()

    # 수집 실행
    collector = KpopTradeCollector()
    posts = collector.collect(args.artist, args.limit, args.source)

    if not posts:
        print("\n❌ 수집된 게시글이 없습니다.")
        print("💡 API 키 설정을 확인하세요:")
        print("   - REDDIT_APP_ID, REDDIT_SECRET (.env)")
        print("   - SERPAPI_KEY (.env)")
        return

    # 저장
    filename = collector.save_to_jsonl(posts, args.artist)

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
