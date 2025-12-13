# 🎵 K-pop 포토카드 거래 게시글 수집 스크립트

Reddit에서 K-pop 아이돌 포토카드 거래 게시글(WTS/WTB/WTT)을 자동으로 수집하는 스크립트입니다.

## 📁 폴더 구조

```
share/
├── README.md                    # 이 파일 (사용 설명서)
├── collect_kpop_trade.py        # SerpAPI 기반 수집 (v1)
├── collect_kpop_trade_v2.py     # SerpAPI + Reddit API 통합 수집 (v2) ⭐ 추천
├── requirements.txt             # 필요한 패키지
├── env.example                  # 환경변수 설정 예시
└── sample_data/
    └── seventeen_trade_sample.jsonl  # 수집 결과 예시
```

## 🆚 v1 vs v2 비교

| 항목 | v1 (collect_kpop_trade.py) | v2 (collect_kpop_trade_v2.py) |
|------|---------------------------|-------------------------------|
| 데이터 소스 | SerpAPI만 | **SerpAPI + Reddit API** |
| 예상 수집량 | 60-70개 | **100-200개+** |
| 아티스트 필터 | 기본 | **별명 지원 (SVT, 세븐틴 등)** |
| 추가 정보 | URL, 제목, snippet | **+ 본문, 작성자, 업보트, 댓글수** |
| 설정 난이도 | 쉬움 (키 1개) | 보통 (키 2~3개) |

## 🚀 빠른 시작

### 1. 환경 설정

```bash
# 패키지 설치
pip install -r requirements.txt

# 환경변수 설정
cp .env.example .env
# .env 파일 열어서 SERPAPI_KEY 입력
```

### 2. API 키 발급

#### SerpAPI (필수)
1. [https://serpapi.com/](https://serpapi.com/) 가입
2. 무료 플랜: 월 100회 검색 가능
3. API Key 복사 → `.env` 파일에 `SERPAPI_KEY=your_key` 입력

#### Reddit API (v2 사용 시 권장)
1. [https://www.reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) 접속
2. "create another app..." 클릭 → **script** 타입 선택
3. 생성된 앱에서:
   - `REDDIT_APP_ID`: 앱 이름 아래의 짧은 문자열
   - `REDDIT_SECRET`: "secret" 옆의 긴 문자열
4. `.env` 파일에 추가

### 3. 실행

#### v2 사용 (권장 ⭐)

```bash
# 세븐틴 포토카드 거래글 수집 (SerpAPI + Reddit API)
python collect_kpop_trade_v2.py

# 다른 아이돌로 수집
python collect_kpop_trade_v2.py --artist "BTS"
python collect_kpop_trade_v2.py --artist "Stray Kids"
python collect_kpop_trade_v2.py --artist "NewJeans"

# 수집 개수 조정
python collect_kpop_trade_v2.py --limit 300

# 특정 소스만 사용
python collect_kpop_trade_v2.py --source reddit   # Reddit API만
python collect_kpop_trade_v2.py --source serpapi  # SerpAPI만
python collect_kpop_trade_v2.py --source both     # 둘 다 (기본값)
```

#### v1 사용 (SerpAPI만)

```bash
# 기본 실행
python collect_kpop_trade.py

# 다른 아이돌로 수집
python collect_kpop_trade.py --artist "BTS"

# 수집 개수 조정
python collect_kpop_trade.py --limit 50
```

## 📊 수집되는 데이터

### 거래 유형
- **WTS** (Want To Sell) - 팔고 싶어요
- **WTB** (Want To Buy) - 사고 싶어요
- **WTT** (Want To Trade) - 교환해요
- **ISO** (In Search Of) - 찾고 있어요

### 출력 파일 (JSONL 형식)

#### v1 출력
```json
{
  "url": "https://www.reddit.com/r/kpopforsale/comments/...",
  "title": "[WTS][USA] Seventeen Photocards $3 each",
  "snippet": "All photocards are in mint condition...",
  "source": "reddit",
  "lang": "en",
  "queried_at": "2025-12-10T11:46:35"
}
```

#### v2 출력 (더 많은 정보 포함)
```json
{
  "url": "https://reddit.com/r/kpopforsale/comments/...",
  "title": "[WTS][USA] Seventeen Photocards $3 each",
  "content": "All photocards are in mint condition. Shipping from USA...",
  "snippet": "All photocards are in mint condition...",
  "author": "username123",
  "subreddit": "kpopforsale",
  "source": "reddit_api",
  "lang": "en",
  "created_at": "2025-12-10T11:46:35",
  "score": 15,
  "num_comments": 8,
  "queried_at": "2025-12-10T12:00:00"
}
```

## 🔑 주요 키워드

| 영어 | 의미 | 예시 |
|------|------|------|
| WTS | 판매 | [WTS] Selling SVT PCs |
| WTB | 구매 | [WTB] Looking for Mingyu PC |
| WTT | 교환 | [WTT] Trading Seventeen PCs |
| ISO | 찾음 | ISO Vernon Birthday PC |
| PC | 포토카드 | SVT PC for sale |
| POB | Pre-Order Benefit | FML POB trade |

## ⚠️ 주의사항

1. **API 사용량**: SerpAPI 무료 플랜은 월 100회 제한
2. **Rate Limiting**: 과도한 요청 시 차단될 수 있음
3. **데이터 활용**: 수집한 데이터는 연구/분석 목적으로만 사용

## 💡 활용 아이디어

- 가격 동향 분석: 어떤 멤버 포카가 가장 비싼지?
- 인기 분석: 어떤 앨범/버전이 가장 많이 거래되는지?
- 시장 조사: 거래 게시글 패턴, 지역별 분포 등

## 📞 문의

궁금한 점이 있으면 언제든 물어보세요!


