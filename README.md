# DesignMap - 디자인권 분류 에이전트

전 세계 특허청에 공개된 디자인권(IP)의 대표도면·육면도·서지정보를 분석하여
외관 디자인 특성에 따라 분류하고, 디자인 로드맵을 통해 미래 트렌드를 예측하는 에이전트.

---

## 1. 설치

```bash
git clone <repo-url>
cd designmap
pip install -e ".[dev]"
```

설치가 끝나면 `designmap` 명령을 사용할 수 있습니다.

```bash
designmap --help
```

### 환경변수 설정

| 변수 | 필요 단계 | 비고 |
|------|-----------|------|
| `ANTHROPIC_API_KEY` | `propose`, `classify`, `report`, (스캔 PDF의 `parse-pdf`) | **필수** (AI 분석) |
| `KIPRIS_API_KEY` | `collect --source kipris` | 선택 (한국 API 수집 시) |

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export KIPRIS_API_KEY="..."        # 선택
```

> **API 키 없이 가능한 단계**: `template`, `load`, `screen`(규칙 기반 케이스), 텍스트 기반 PDF의 `parse-pdf`

---

## 2. 전체 워크플로우

```
[데이터 입력]      [노이즈 제거]   [기준 협의]        [분류]      [예측]
PDF/Excel/API  →   screen     →   propose      →   classify  →  report
parse-pdf          1차 스크리닝    AI 기준 제안       AI 분류      트렌드
load                              ↕ 사용자 검토                   리포트
collect                           (status: approved)
```

---

## 3. 단계별 실행

### Step 1. 데이터 입력 (택1)

#### (A) PDF 원문공보에서 추출 — 권장

하드디스크에 국가별 폴더로 PDF를 정리한 뒤 실행:

```bash
designmap parse-pdf /data/patents/korea --office KIPO
designmap parse-pdf /data/patents/us    --office USPTO
designmap parse-pdf /data/patents/eu    --office EUIPO
designmap parse-pdf /data/patents/china --office CNIPA
designmap parse-pdf /data/patents/japan --office JPO
```

- 서지사항(출원번호·물품명·출원인·로카르노 분류 등)과 도면 이미지를 자동 추출
- 텍스트 추출이 안 되는 스캔 PDF는 Claude Vision OCR로 자동 폴백 (API 키 필요)
- 텍스트 추출만 사용하려면 `--no-vision`
- 결과: `data/parsed_patents.xlsx` + DB 저장

#### (B) Excel 수동 입력

```bash
designmap template                                    # 템플릿 생성 → data/template.xlsx
# 템플릿을 채운 뒤
designmap load data/template.xlsx --drawings-dir /path/to/images
```

#### (C) API 자동 수집

```bash
designmap collect --source kipris --locarno 14-03 --keyword 스마트폰
```

---

### Step 2. 1차 스크리닝 (노이즈 제거)

```bash
designmap screen \
  --locarno 14-03 \
  --keywords "스마트폰,휴대폰,smartphone" \
  --exclude  "케이블,충전기,필름"
```

- 로카르노 불일치·제외 키워드 매칭 → **규칙 기반으로 즉시 제외** (API 불필요)
- 애매한 건만 Claude Vision이 도면을 보고 판단 (API 필요)

---

### Step 3. 분류 기준 제안 (AI)

```bash
designmap propose --locarno 14-03 --context "스마트폰 외관 디자인 트렌드 분석"
```

- AI가 도면 + PEST 분석 기반으로 분류 차원을 제안
- 결과: `data/proposed_criteria.json`

### Step 4. 기준 검토·확정 (사용자)

`data/proposed_criteria.json`을 열어 차원/값을 수정한 뒤,
**`"status": "proposed"` → `"status": "approved"`** 로 변경하고 저장.

### Step 5. 디자인권 분류 (AI)

```bash
designmap classify
```

- 확정 기준으로 각 디자인권을 분류 → `data/classification_results.json`

### Step 6. 트렌드 예측 리포트 (AI)

```bash
designmap report --context "2025년 이후 스마트폰 디자인 방향 예측"
```

- 연도별·지역별·특징별 통계 + PEST 결합 → `data/trend_report.md`

---

## 4. 빠른 체험 (샘플 데이터, API 키 없이)

```bash
# 1) 템플릿 생성 후 직접 채우거나, 아래처럼 샘플 작성
designmap template --output data/sample.xlsx

# 2) 로드
designmap load data/sample.xlsx

# 3) 스크리닝 (명확한 케이스는 규칙 기반으로 처리)
designmap screen --locarno 14-03 --keywords "스마트폰,smartphone"
```

여기까지는 `ANTHROPIC_API_KEY` 없이 동작합니다.
`propose` 이후 단계부터 API 키가 필요합니다.

---

## 5. 지원 특허청

| 코드 | 특허청 | PDF 파싱 | API 수집 |
|------|--------|:---:|:---:|
| KIPO | 한국특허청 | ✅ | ✅ (KIPRIS) |
| USPTO | 미국특허상표청 | ✅ | ✅ (PatentsView) |
| EUIPO | 유럽연합지식재산청 | ✅ | ✅ (eSearch) |
| CNIPA | 중국국가지식산권국 | ✅ | △ (Google Patents 경유) |
| JPO | 일본특허청 | ✅ | ✅ (J-PlatPat) |

---

## 6. 개발

```bash
pip install -e ".[dev]"
pytest                    # 전체 테스트
```

## 7. 디렉토리 구조

```
src/
├── collectors/   # 데이터 수집 (PDF 파서, KIPRIS/USPTO/EUIPO/CNIPA/JPO API, Excel)
├── screening/    # 1차 스크리닝 (로카르노 + 키워드 + AI Vision)
├── classifier/   # 분류 기준 제안 & 디자인 분류
├── analysis/     # 로드맵 분석 & 트렌드 예측
├── models/       # 데이터 모델 (Pydantic)
├── utils/        # DB, 이미지 로더
└── cli.py        # Typer CLI
```
