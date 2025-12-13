# 📢 [공유] Reddit K-pop 거래 게시글 수집 스크립트

## 📁 공유 폴더
`share/`

---

## 🎯 공유 배경

안녕하세요!

약 2달 전에 **K-pop 포토카드 사기 거래 사례 조사**를 위해 Reddit 게시글을 수집하고, 사기 패턴을 분석하려고 작성했던 코드가 있었는데요.

이번에 코드를 정리해서 **팀원분들도 쉽게 사용할 수 있도록 수정**해서 공유드립니다.

---

## 📋 이번 주 리서치 방향

이번 주는 **X(트위터)** 중심으로 사용자 리서치를 진행하기로 했지만,

혹시 **AI 엔지니어 팀**에서 Reddit에서도 추가적인 데이터 수집이 필요하다고 느끼신다면,
**건호님, 채현님** 피드백 주시면 감사하겠습니다! 🙏

---

## 📦 공유 내용

### 폴더 구조
```
share/
├── README.md                    # 상세 사용 설명서
├── collect_kpop_trade.py        # 메인 수집 스크립트
├── requirements.txt             # 필요한 패키지
├── env.example                  # API 키 설정 예시
└── sample_data/
    └── seventeen_trade_sample.jsonl  # 예시 데이터 (세븐틴)
```

### 예시 샘플
**세븐틴 포토카드 거래 게시글**을 수집해봤습니다.
- WTS (Want To Sell) - 팔고 싶어요
- WTB (Want To Buy) - 사고 싶어요
- WTT (Want To Trade) - 교환해요

`sample_data/seventeen_trade_sample.jsonl` 파일에서 실제 수집 결과를 확인하실 수 있습니다.

---

## 🔧 사용 방법

```bash
# 1. 패키지 설치
pip install -r requirements.txt

# 2. API 키 설정
cp env.example .env
# .env 파일에서 SERPAPI_KEY 입력

# 3. 실행
python collect_kpop_trade.py --artist "Seventeen"
python collect_kpop_trade.py --artist "BTS"
python collect_kpop_trade.py --artist "NewJeans"
```

코드 직접 실행해보시고, 필요에 맞게 수정해서 사용하시면 됩니다!

---

## ❓ 기술적인 부분 설명

### Q. Reddit API를 직접 쓰는 건가요?

**아니요, Reddit API를 직접 사용하지 않습니다.**

이 스크립트는 **SerpAPI**를 통해 **Google 검색 결과**에서 Reddit 게시글을 수집하는 방식입니다.

```
[우리 스크립트] → [SerpAPI] → [Google 검색] → [Reddit 게시글 URL 수집]
```

### Q. 왜 Reddit API를 직접 안 쓰나요?

| 방식 | 장점 | 단점 |
|------|------|------|
| **Reddit API 직접** | 정확한 데이터 | OAuth 인증 복잡, Rate limit 엄격 (분당 60회), 승인 필요 |
| **SerpAPI 우회** | 설정 간단, 키 하나로 바로 사용 | 월 100회 제한 (무료), 검색 결과 기반이라 누락 가능 |

**결론**: 빠른 프로토타이핑과 사례 조사 목적으로는 SerpAPI가 더 편리합니다.
본격적인 대규모 수집이 필요하면 Reddit API 직접 연동을 검토해야 합니다.

### Q. 왜 65~70개 정도만 수집되나요?

1. **SerpAPI 무료 플랜 한계**: 월 100회 검색 제한
2. **중복 제거**: 여러 키워드로 검색하면 같은 게시글이 중복으로 나옴
3. **거래 키워드 필터링**: WTS, WTB, WTT 등 실제 거래 게시글만 남김

```
검색 결과 110개 → 중복 제거 → 거래 필터 → 최종 65개
```

더 많은 데이터가 필요하면:
- SerpAPI 유료 플랜 업그레이드 ($50/월 5,000회)
- 또는 Reddit API 직접 연동

---

## 💬 피드백 요청

- 다른 아티스트/키워드 추가가 필요하신가요?
- 수집 데이터 형식 변경이 필요하신가요?
- Reddit 외 다른 플랫폼 수집이 필요하신가요?

편하게 말씀해주세요! 🙌

---

감사합니다! 🎵

