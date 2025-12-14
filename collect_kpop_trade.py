#!/usr/bin/env python3
"""
🎵 K-pop 포토카드 거래 게시글 수집 스크립트

Reddit에서 K-pop 아이돌 포토카드 WTS/WTB/WTT 거래 게시글을 수집합니다.

사용법:
    python collect_kpop_trade.py                      # 세븐틴 기본 수집
    python collect_kpop_trade.py --artist "BTS"       # 다른 아이돌
    python collect_kpop_trade.py --limit 50           # 수집 개수 조정
"""

import argparse
import json
import os
import sys
from datetime import datetime
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
    YOUTUBE = "youtube"
    WEB = "web"


class SearchResult(BaseModel):
    """검색 결과 모델"""
    url: str = Field(..., description="결과 URL")
    title: str = Field(..., description="제목")
    snippet: str = Field(..., description="내용 미리보기")
    source: SearchSource = Field(..., description="검색 소스")
    lang: str = Field(..., description="언어 코드")
    queried_at: datetime = Field(default_factory=datetime.now, description="검색 시간")


# ============================================================
# SerpAPI 검색 클래스
# ============================================================

class SerpSearcher:
    """SerpAPI 기반 검색 클래스"""

    def __init__(self, api_key: Optional[str] = None, output_dir: str = "data"):
        self.api_key = api_key or os.getenv("SERPAPI_KEY")
        if not self.api_key:
            raise ValueError("❌ SERPAPI_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
        
        self.base_url = "https://serpapi.com/search"
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def build_query(self, keywords: List[str], source: SearchSource) -> str:
        """검색 쿼리 생성"""
        keyword_query = " AND ".join(keywords)
        
        if source == SearchSource.REDDIT:
            return f"{keyword_query} site:reddit.com"
        elif source == SearchSource.YOUTUBE:
            return f"{keyword_query} site:youtube.com"
        return keyword_query

    @retry(
        retry=retry_if_exception_type((requests.exceptions.RequestException, TimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def _make_request(self, params: dict) -> dict:
        """API 요청 (자동 재시도 포함)"""
        response = requests.get(self.base_url, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        if "error" in data:
            raise ValueError(f"SerpAPI 오류: {data.get('error')}")
        return data

    def search(
        self,
        keywords: List[str],
        source: SearchSource = SearchSource.REDDIT,
        language: str = "en",
        max_results: int = 10,
    ) -> List[SearchResult]:
        """검색 실행"""
        query = self.build_query(keywords, source)
        
        params = {
            "q": query,
            "api_key": self.api_key,
            "num": min(max_results, 100),
            "hl": language,
            "gl": "kr" if language == "ko" else "us",
            "tbs": "qdr:m6",  # 최근 6개월
        }

        try:
            data = self._make_request(params)
        except ValueError as e:
            if "quota" in str(e).lower() or "limit" in str(e).lower():
                print(f"⚠️  API 할당량 초과: {e}")
                return []
            raise

        results = []
        for item in data.get("organic_results", []):
            try:
                result = SearchResult(
                    url=item.get("link", ""),
                    title=item.get("title", ""),
                    snippet=item.get("snippet", ""),
                    source=source,
                    lang=language,
                )
                results.append(result)
            except Exception as e:
                continue

        return results


# ============================================================
# 거래 게시글 수집 함수
# ============================================================

def get_trade_keywords(artist: str) -> dict:
    """아티스트별 거래 키워드 생성"""
    
    # 아티스트 이름 변형
    artist_lower = artist.lower()
    
    keywords = {
        'en': [
            # WTS (판매)
            ["WTS", artist, "photocard"],
            ["WTS", artist, "pc"],
            ["selling", artist, "photocard"],
            ["for sale", artist, "photocard"],
            
            # WTB (구매)
            ["WTB", artist, "photocard"],
            ["WTB", artist, "pc"],
            ["buying", artist, "photocard"],
            ["looking for", artist, "photocard"],
            ["ISO", artist, "photocard"],
            
            # WTT (교환)
            ["WTT", artist, "photocard"],
            ["trade", artist, "photocard"],
            ["trading", artist, "pc"],
            
            # 서브레딧 특정
            ["site:reddit.com/r/kpopforsale", artist],
            ["site:reddit.com/r/kpopcollections", artist, "trade"],
        ],
        'ko': [
            [artist, "포토카드", "양도"],
            [artist, "포카", "양도"],
            [artist, "포토카드", "판매"],
            [artist, "포카", "구해요"],
            [artist, "포카", "삽니다"],
            [artist, "포카", "팝니다"],
        ]
    }
    
    return keywords


def filter_trade_posts(results: List[SearchResult]) -> List[SearchResult]:
    """거래 관련 게시글만 필터링"""
    trade_keywords = [
        'wts', 'wtb', 'wtt', 'trade', 'trading', 'selling', 'buying', 
        'for sale', 'iso', '양도', '판매', '구해', '삽니다', '팝니다', '교환'
    ]
    
    filtered = []
    for result in results:
        combined = (result.title + " " + result.snippet).lower()
        if any(kw in combined for kw in trade_keywords):
            filtered.append(result)
    
    return filtered


def collect_trade_posts(artist: str = "Seventeen", limit: int = 100, languages: List[str] = None):
    """거래 게시글 수집 메인 함수"""
    
    if languages is None:
        languages = ["en"]
    
    print("=" * 60)
    print(f"🎵 {artist} 포토카드 거래 게시글 수집")
    print("=" * 60)
    print(f"🎯 Target: WTS/WTB/WTT 거래 게시글")
    print(f"🌐 Languages: {', '.join(languages)}")
    print(f"📊 Limit: ~{limit} posts")
    print()

    # 검색기 초기화
    try:
        searcher = SerpSearcher()
        print("✅ SerpAPI 연결 성공")
    except ValueError as e:
        print(f"❌ {e}")
        print("💡 .env 파일에 SERPAPI_KEY를 설정하세요")
        return None

    # 키워드 가져오기
    all_keywords = get_trade_keywords(artist)

    # 검색 실행
    all_results = []
    for lang in languages:
        if lang not in all_keywords:
            continue
        
        keywords_list = all_keywords[lang]
        print(f"\n🌐 Language: {lang.upper()} ({len(keywords_list)} 키워드)")
        
        for i, keywords in enumerate(keywords_list, 1):
            print(f"  [{i}/{len(keywords_list)}] {' + '.join(keywords)}")
            
            try:
                results = searcher.search(
                    keywords=keywords,
                    source=SearchSource.REDDIT,
                    language=lang,
                    max_results=10
                )
                print(f"    ✅ {len(results)} results")
                all_results.extend(results)
            except Exception as e:
                print(f"    ⚠️ No results")

    # 중복 제거
    seen_urls = set()
    unique_results = []
    for result in all_results:
        if result.url not in seen_urls:
            unique_results.append(result)
            seen_urls.add(result.url)
    
    print(f"\n📊 중복 제거 후: {len(unique_results)}개")

    # 거래 게시글 필터링
    filtered_results = filter_trade_posts(unique_results)
    print(f"🔍 거래 키워드 필터 후: {len(filtered_results)}개")

    # 제한 적용
    if len(filtered_results) > limit:
        filtered_results = filtered_results[:limit]

    # 저장
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    artist_safe = artist.lower().replace(" ", "_")
    filename = Path("data") / f"{artist_safe}_trade_{timestamp}.jsonl"
    Path("data").mkdir(exist_ok=True)
    
    with open(filename, "w", encoding="utf-8") as f:
        for result in filtered_results:
            data = {
                "url": result.url,
                "title": result.title,
                "snippet": result.snippet,
                "source": result.source.value,
                "lang": result.lang,
                "queried_at": result.queried_at.isoformat(),
            }
            f.write(json.dumps(data, ensure_ascii=False) + "\n")

    print(f"\n{'=' * 60}")
    print(f"✅ 수집 완료: {len(filtered_results)}개 거래 게시글")
    print(f"💾 저장: {filename}")
    print("=" * 60)

    # 샘플 출력
    print("\n📋 수집된 거래 게시글 샘플:")
    for i, result in enumerate(filtered_results[:10], 1):
        title = result.title[:55] + "..." if len(result.title) > 55 else result.title
        print(f"  {i}. {title}")
    
    if len(filtered_results) > 10:
        print(f"  ... 외 {len(filtered_results) - 10}개")

    return filename


# ============================================================
# 메인 실행
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="K-pop 포토카드 거래 게시글 수집",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python collect_kpop_trade.py                    # 세븐틴 수집
  python collect_kpop_trade.py --artist "BTS"     # BTS 수집
  python collect_kpop_trade.py --artist "TWICE"   # 트와이스 수집
  python collect_kpop_trade.py --limit 50         # 50개만 수집
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
        default=100,
        help="최대 수집 개수 (기본: 100)",
    )
    parser.add_argument(
        "--languages",
        type=str,
        default="en",
        help="언어 (쉼표로 구분, 기본: en)",
    )

    args = parser.parse_args()
    languages = [l.strip() for l in args.languages.split(",")]

    collect_trade_posts(args.artist, args.limit, languages)


if __name__ == "__main__":
    main()



