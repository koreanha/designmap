# DesignMap - 디자인권 분류 에이전트

디자인 로드맵 분석 및 미래 디자인 트렌드 예측을 위한 디자인권(IP) 분류 에이전트.

## 아키텍처

```
src/
├── collectors/     # 데이터 수집 (KIPRIS API, 수동 Excel 입력)
├── screening/      # 1차 스크리닝 (로카르노 + 키워드 + AI Vision)
├── classifier/     # 분류 기준 제안 & 디자인 분류
├── analysis/       # 로드맵 분석 & 트렌드 예측
├── models/         # 데이터 모델 (Pydantic)
├── utils/          # DB, 이미지 로더
└── cli.py          # Typer CLI
```

## 워크플로우

1. `designmap collect` 또는 `designmap load` - 데이터 수집/입력
2. `designmap screen` - 1차 스크리닝 (노이즈 제거)
3. `designmap propose` - AI가 분류 기준 제안 → 사용자 검토/확정
4. `designmap classify` - 확정 기준으로 분류
5. `designmap report` - 트렌드 예측 리포트 생성

## 개발

```bash
pip install -e ".[dev]"
pytest
```

## 환경변수

- `ANTHROPIC_API_KEY` - Claude API
- `KIPRIS_API_KEY` - 한국특허정보원 API (optional)
