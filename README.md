# Gangnam Beauty Guide — Multi-Step Review Syndication, Photo-Integrity & Graph-Repair Engine

**Live Interactive Workbench:** [https://anhminhzui-dev.github.io/gbg-syndication-workbench/](https://anhminhzui-dev.github.io/gbg-syndication-workbench/)

Built for **Gangnam Beauty Guide** (`gangnambeautyguide.com` / `gangnambeauty.guide`). Implements Anthropic's **Prompt-Chaining + Deterministic Gate + Evaluator-Optimizer** architecture and runs directly against the live Next.js RSC payloads pulled from `gangnambeautyguide.com` on `2026-10-27` (`182` clinics, `467` doctors, `90` reviews).

---

## Candidate Verification Package — Vo Ba Hoang Minh
- **AI engineering CV / resume:** https://anhminhzui-dev.github.io/anhminhzui-dev/Vo_Ba_Hoang_Minh_CV.pdf
- **Applied AI & VFX / Production Mentor CV:** https://anhminhzui-dev.github.io/anhminhzui-dev/Vo_Ba_Hoang_Minh_VFX_AI_Mentor_CV.pdf
- **Portfolio:** https://anhminhzui-dev.github.io/anhminhzui-dev/
- **Frontier Graphics & Autonomous 3D Systems:** https://anhminhzui-dev.github.io/anhminhzui-dev/#graphics
- **GitHub:** https://github.com/anhminhzui-dev
- **Role-specific AI evaluation repos:** https://github.com/anhminhzui-dev/failclosed-eval | https://github.com/anhminhzui-dev/mcp-trajectory-judge
- **Recent AI research — Constructing Language Judgments (technical report):** https://doi.org/10.5281/zenodo.22675789
- **Gnomon product UI preview (sample data):** https://anhminhzui-dev.github.io/anhminhzui-dev/gnomon/product/
- **LinkedIn:** https://www.linkedin.com/in/minh-v%C3%B5-b%C3%A1-ho%C3%A0ng-287942366/

---

## 1. Live Production Audit Receipt (`gangnambeautyguide.com`, 2026-10-27)

| Live Dataset | Rows Audited | Measured Production Finding | Delivered Fix in This Repo |
|---|---|---|---|
| **`/en/doctors`** | `467` | • **`21` duplicate spelling-twin rows** (same Hangul surgeon & identical `rating`/`reviewCount` split by Revised vs. McCune-Reischauer romanization, e.g. `이강우`: `dr-60` `"Gang-Woo Lee"` vs. `dr-136` `"Kang-Woo Lee"`, both `4.6 ★ / 999 reviews`).<br>• **`4` Korean homonym rows (`동명이인`)**: `김형준` (`dr-92` `132` reviews vs. `dr-65` `939` reviews) and `김세영` (`dr-155` vs. `dr-324`).<br>• **`1` row-shift corruption**: `dr-10` pairs `koreanName: "이정환"` (Lee) with `romanizedName: "Chan-Eol Seo"`.<br>• **`60` bare-surname / missing-Hangul rows** (e.g. `dr-131: "Creamy"`, `dr-128: "Park"`). | [`data/doctors_repaired_467.json`](data/doctors_repaired_467.json) + [`runs/public_correction_log.jsonl`](runs/public_correction_log.jsonl) (`82` logged corrections). |
| **`/en/reviews`** | `90` | `90 of 90 (100%)` come from a single source (`GangnamUnni`, scraped `2026-04-12` to `2026-04-13`), covering only `12 of 182` clinics (`6.6%`) and omitting `procedureSlugs` and `isRevision`. | [`data/reviews_enriched_90.json`](data/reviews_enriched_90.json) (`59 of 90` backfilled with canonical procedure slugs + SHA-256 provenance). |
| **`/en/tools/tax-refund`** | `1` calculator | Live calculator still tells 2026 patients they receive a 10% VAT refund at the airport. Under **Korean Restriction of Special Taxation Act Article 107-3 (`조세특례제한법 제107조의3`)**, the foreign cosmetic surgery VAT refund **officially sunset on December 31, 2025**. | Stage 1 & Stage 3 compute **2026 True Out-of-Pocket Cost** (`+10%` non-refundable VAT on `부가세 별도` domestic event prices). |

---

## 2. The 4-Stage Multi-Step Agentic Workflow (`gbg_pipeline.py`)

```text
Raw Korean Review (GangnamUnni / Babitalk / Sungyesa / NaverCafe)
  │
  ├─► Stage 1: ClinicalExtractorAgent (Prompt Chain Step 1)
  │     Extracts procedure slugs, local KRW price (만원), VAT-excluded flags,
  │     Factory (공장형/상담실장 counselor-led) vs. Boutique (1인 원장 doctor-led) signals,
  │     and Korean consonant-initial masking (초성, e.g. 'ㄷㅇ성형외과' used on Sungyesa to evade Art. 70 defamation suits).
  │
  ├─► Stage 2: Deterministic Entity, Chosung & VFX Photo Gate
  │     • Blocks KFTC sponsored viral ads (소정의 원고료) & broker WeChat/Kakao IDs -> HOLD
  │     • Resolves clinic & surgeon via Hangul Jamo + phonetic equivalence while protecting homonyms (동명이인)
  │     • VFX Before/After Photo Exposure Gate (의료법 제56조): flags >0.75 EV background lighting boost -> QUARANTINE
  │     • Cross-platform 3-gram shingle fingerprint deduplication (GangnamUnni <-> Babitalk)
  │
  ├─► Stage 3: EditorialTransformerAgent (Prompt Chain Step 2)
  │     Drafts neutral 3rd-person clinical report + 2026 VAT-inclusive cost disclosure.
  │
  └─► Stage 4: MedicalHygieneEvaluator (Evaluator-Optimizer Loop, max 1 retry)
        Audits Stage 3 for dropped KRW figures, smoothed-over complications, or promotional superlatives;
        triggers an automated rewrite before emitting GO / QUARANTINE / HOLD + SHA-256 receipt.
```

---

## 3. Run It Locally in 10 Seconds

```bash
python -m pytest test_gbg_pipeline.py -v
python build_artifacts.py
```

```text
8 passed in 0.23s
BUILD SUMMARY: {
  "total_live_doctors": 467,
  "clean_canonical": 381,
  "merged_spelling_twins": 21,
  "homonym_protected": 4,
  "jamo_row_shift_quarantined": 1,
  "bare_surname_quarantined": 60
}
Reviews enriched: 90 (procedures backfilled: 59)
Correction log rows: 82
```
