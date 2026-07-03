# OntoQuant

온톨로지 기반 퀀트 포트폴리오 리스크 시스템. 종목·섹터·기업·재무·공시·뉴스를
하나의 그래프로 연결하고, 검증된 근거가 있는 제안만 승인으로 이어진다.

## 구조

```
ontology/     스키마 단일 진실 소스 (YAML). 수정 후 반드시 codegen 재실행
pipeline/     Python 패키지 ontoquant (수집→계산→이벤트→전파→인사이트→제안→export)
mcp-server/   Claude Code MCP 서버 (조회/RAG/액션/시나리오/publish)
dashboard/    Next.js 정적 export (GitHub Pages). 데이터는 public/data/*.json 만
data/         계층형 정본: source(수집) / computed(파생) / writeback(편집·결정)
notes/        세션 간 교훈 기록 (git 미추적, 파일당 교훈 1개, 첫 줄 '요약:')
```

## 필수 명령

```bash
.venv/bin/python -m pytest pipeline/tests            # 테스트 (커밋 전 필수)
.venv/bin/python -m ontoquant.run_daily --stage all  # 전체 파이프라인
.venv/bin/python scripts/codegen_ts.py               # 스키마 변경 시 (--check 로 드리프트 검사)
.venv/bin/python -m ontoquant.quality                # 데이터 불균형 진단
cd dashboard && npm run build                        # 정적 빌드 (out/)
```

## 절대 규칙

1. **비밀 보호**: `api-key.txt`, `huggingface.txt` 는 절대 커밋 금지. 커밋 전
   `git ls-files --cached | grep -i "api-key\|huggingface"` 가 비어 있어야 한다.
2. **PIT 규율 (누출 방지)**: 시뮬레이션 날짜 t 의 모든 판단은 knownAt ≤ t 인
   정보만 사용한다. 과거 판정에 full-sample 통계를 쓰는 코드는 버그다.
   이벤트 severity 는 소급 수정 금지 (severityBasis 가 감사 근거).
3. **검증 게이트**: 인사이트는 이벤트 스터디(n≥10, |tBmp|≥2), 제안은 백테스트
   (walk-forward 는 DSR≥0.95 포함)를 통과해야 승인 가능. 게이트를 우회하는
   코드를 추가하지 않는다. 시도(ruleHash) 장부는 지울 수 없다.
4. **상태 변경은 액션으로만**: portfolio.json 등 writeback 은 ActionEngine
   (제출 기준 + 감사 로그) 경유. 직접 파일 수정은 시드/마이그레이션뿐.
5. **거래 규칙**: `tradable: false` 종목(코스피 지수 프록시 등)은 매수/매도/보유
   불가 — 데이터·팩터 용도로만 쓴다. 개별 주식 보유는 riskLimits.maxHoldings
   (기본 15) 를 넘을 수 없다. ETF 는 이 수에서 제외.

## 문구 원칙 (대시보드)

- 엠대시(—) 금지. 짧은 문장. 학술어는 풀어 쓰고 정말 궁금할 것만 ? 툴팁.
- MCP/게이트/스테이징 같은 내부 용어를 사용자 화면에 노출하지 않는다.
- DESIGN.md 디자인 시스템(모노크롬+파스텔 색블록, pill 버튼) 준수.

## 작업 방식

- Phase 완료 시 general-purpose 서브에이전트로 스펙 체크리스트 대조 검증.
- 브라우저 자동화(claude-in-chrome)는 토큰 소모가 크므로 최종 확인 1회만.
  평소엔 빌드 산출물(dashboard/out)을 grep/node 로 검사한다.
- 교훈은 notes/ 에 기록 (기존 노트 갱신 우선, 틀린 노트는 삭제).
- 커밋 정체성: dyseo521 <dyseo521@gmail.com>.

## 함정 (notes/ 상세)

- parquet 읽기는 `astype("datetime64[ns]")` 필수 (us 해상도로 돌아옴).
- Stooq 사용 불가(안티봇), Yahoo RSS 는 429 잦음(보조 신호로만).
- DART status "013" 은 '데이터 없음'이지 에러가 아니다.
- KP 군집 보정은 시장 차감 잔차 상관으로 (원시 상관이면 과보정).
