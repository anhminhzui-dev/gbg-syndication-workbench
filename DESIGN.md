# DESIGN.md — Gangnam Beauty Guide Syndication & Graph-Repair Workbench

## 1. Visual Register & Baseline Fidelity
Built on the verified **Anthropic Research Warm-Paper Editorial System** (`DESIGN_BASELINE_REFERENCES.md` & `DESIGN_QA_RUBRIC.md`):
- **Primary Paper (`--bg-paper`):** `#FAF9F5`
- **Recessed Surface (`--bg-card`):** `#F0EEE6`
- **Primary Ink (`--ink`):** `#141413`
- **Muted Copy (`--muted`):** `#5E5D59`
- **Hairline Ledger Rule (`--rule`):** `#D1CFC5`
- **Semantic Verdict Accents (disciplined 3-state system):**
  - `GO` (Verified & Admitted): `#285A4D` (Botanical Clinical Green)
  - `QUARANTINE` (Advisory Escalation): `#D97757` (Warm Terracotta)
  - `HOLD` (Fail-Closed Refusal): `#8B261D` (Deep Crimson)

## 2. Typography & Hierarchy
- **Display & Editorial Headings:** `Georgia, 'Times New Roman', serif` (`<= 75ch` measure, deliberate scale steps: `2.5rem`, `1.5rem`, `1.125rem`).
- **UI & Ledger Tables:** `system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`.
- **Hashes, Refusal Codes & KRW Math:** `ui-monospace, 'Cascadia Mono', 'Consolas', monospace`.

## 3. First-Viewport & Interactive Evidence Contract (`1440px` & `390px`)
1. **5-Second Read:** Title, 1-sentence architectural thesis, and live audit counters (`467` live doctors audited -> `102` defects isolated; `90` live reviews backfilled; `8/8` pytest checks passing) visible above the fold without scrolling.
2. **Interactive 4-Stage Agent Stepper:** Inspect intermediate JSON state across `Stage 1: Clinical & Chosung Extractor` -> `Stage 2: Entity & Before/After Photo Gate` -> `Stage 3: 2026 VAT-Adjusted Writer` -> `Stage 4: Evaluator-Optimizer Loop`.
3. **Interactive Before/After Photo Exposure Gate (`의료법 제56조`):** Slider inspecting background luminance delta (`ΔEV`) and aspect-ratio warp between Before and After clinic photos.
4. **Live Production Repair Table:** Searchable ledger of the actual `467` doctors and `90` reviews pulled from `gangnambeautyguide.com` RSC payloads on `2026-10-27`.
5. **Accessibility:** All interactive targets `>= 44px`, keyboard navigable, `@media (prefers-reduced-motion: reduce)` respected, zero horizontal overflow at `390px`.
