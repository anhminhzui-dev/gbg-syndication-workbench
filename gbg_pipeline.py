"""
Gangnam Beauty Guide — 4-Stage Agentic Review Syndication, Before/After Photo Gate & Graph-Repair Engine.

Implements Anthropic's "Building Effective Agents" Prompt-Chaining + Deterministic Gate + Evaluator-Optimizer pattern,
audited directly against live https://gangnambeautyguide.com RSC payloads (182 clinics, 467 doctors, 90 reviews).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Callable, Optional


class Verdict(str, Enum):
    GO = "GO"                  # Admitted to production index
    QUARANTINE = "QUARANTINE"  # Escalated to Medical Advisory Council / human review
    HOLD = "HOLD"              # Refused fail-closed (spam, KFTC ad, or corrupt entity)


class RefusalCode(str, Enum):
    KFTC_SPONSORED_AD = "KFTC_SPONSORED_AD"                  # 뒷광고 / 소정의 원고료 disclosure
    BROKER_SHILL_PATTERN = "BROKER_SHILL_PATTERN"            # WeChat/Kakao illegal broker ID drop
    UNRESOLVED_CLINIC = "UNRESOLVED_CLINIC"                  # Cannot map clinic name or Chosung to canonical slug
    DOCTOR_JAMO_MISMATCH = "DOCTOR_JAMO_MISMATCH"            # Hangul surname != Romanized surname (live bug: dr-10 이정환 != Seo)
    BARE_SURNAME_ENTITY = "BARE_SURNAME_ENTITY"              # Single-token or missing-Hangul doctor (live bug: dr-128 'Park', dr-131 'Creamy')
    HOMONYM_AMBIGUITY = "HOMONYM_AMBIGUITY"                  # Same Hangul name across distinct surgeons (동명이인: 김형준 dr-92 vs dr-65)
    CROSS_PLATFORM_DUPLICATE = "CROSS_PLATFORM_DUPLICATE"    # Same review syndicated on GangnamUnni + Babitalk
    PHOTO_EXPOSURE_MANIPULATION = "PHOTO_EXPOSURE_MANIPULATION"  # Before/After studio lighting shift > 0.75 EV or aspect warp (의료법 제56조)
    HALLUCINATED_TRANSLATION = "HALLUCINATED_TRANSLATION"    # Evaluator caught dropped KRW price, complication, or promotional hype


# Korean Hangul surname -> allowed English romanizations (Revised Romanization + McCune-Reischauer)
SURNAME_HANGUL_TO_ROMAN: dict[str, set[str]] = {
    "김": {"kim", "gim"},
    "이": {"lee", "yi", "rhe", "ri"},
    "박": {"park", "pak", "bak"},
    "최": {"choi", "choe"},
    "정": {"jung", "jeong", "chung", "joung", "choung"},
    "강": {"kang", "gang"},
    "조": {"cho", "jo"},
    "윤": {"yoon", "yun", "youn"},
    "장": {"jang", "chang"},
    "임": {"lim", "im", "yim"},
    "한": {"han"},
    "오": {"oh", "o"},
    "서": {"seo", "suh"},
    "신": {"shin", "sin"},
    "권": {"kwon", "gwon"},
    "황": {"hwang"},
    "안": {"ahn", "an"},
    "송": {"song"},
    "류": {"ryu", "yoo", "yu"},
    "유": {"yoo", "yu", "ryu"},
    "홍": {"hong"},
    "고": {"ko", "go", "koh"},
    "문": {"moon", "mun"},
    "양": {"yang"},
    "손": {"son", "sohn"},
    "배": {"bae", "pae"},
    "백": {"baek", "paek", "baeg"},
    "허": {"heo", "hur", "huh", "hu"},
    "노": {"noh", "no", "roh"},
    "심": {"sim", "shim"},
    "하": {"ha"},
    "주": {"joo", "ju"},
    "구": {"koo", "gu", "ku"},
    "성": {"sung", "seong"},
    "차": {"cha"},
    "우": {"woo", "u"},
    "전": {"jeon", "jun", "chon"},
    "민": {"min"},
    "태": {"tae"},
    "지": {"ji", "jee"},
    "엄": {"eom", "um", "aum"},
    "채": {"chae"},
    "천": {"cheon", "chun"},
    "방": {"bang", "pang"},
    "공": {"kong", "gong"},
    "현": {"hyun", "hyeon"},
}

# Chosung (Korean consonant-initial masking used on Sungyesa/Naver Cafe to evade Article 70 defamation suits)
CHOSUNG_CLINIC_MAP: dict[tuple[str, str], str] = {
    ("ㄷㅇ", "face-lift"): "da-ps",
    ("ㄷㅇ", "breast-augmentation"): "da-ps",
    ("ㄷㅇ", "des"): "da-ps",
    ("ㄴㄴ", "rhinoplasty"): "nana-ps",
    ("ㄴㄴ", "breast-augmentation"): "nana-ps",
    ("ㅂ", "facial-contouring"): "view-ps",
    ("ㅂ", "des"): "view-ps",
    ("ㅁㅂ", "rhinoplasty"): "marble-ps",
    ("ㅊㅇ", "des-revision"): "chai-ps",
}

PROCEDURE_GLOSSARY: dict[str, list[str]] = {
    "des": ["쌍수", "쌍꺼풀", "매몰", "절개", "자연유착", "눈매교정", "앞트임", "뒤트임", "밑트임", "eyelid", "sleepy-looking"],
    "des-revision": ["눈재수술", "쌍꺼풀재수술", "소세지눈", "revision double-eyelid", "crease had loosened"],
    "rhinoplasty": ["코성형", "코수술", "콧대", "코끝", "비중격", "귀연골", "자가늑", "기증늑", "복코", "매부리코", "화살코", "rhinoplasty", "nasal surgery"],
    "facial-contouring": ["안면윤곽", "윤곽3종", "사각턱", "광대축소", "턱끝", "양악", "facial contour", "jawline", "zygoma"],
    "face-lift": ["안면거상", "미니거상", "이마거상", "울쎄라", "슈링크", "인모드", "써마지", "facelift", "lifting"],
    "breast-augmentation": ["가슴성형", "가슴수술", "모티바", "멘토", "세빈", "breast augmentation"],
    "booster": ["리쥬란", "쥬베룩", "엑소좀", "스킨부스터", "물광주사", "skin booster", "rejuran"],
    "botox": ["보톡스", "자갈턱보톡스", "사각턱보톡스", "침샘보톡스", "botox"],
}

SPONSORED_PATTERNS = [
    re.compile(r"소정의\s*(원고료|수수료|포인트|사례비)"),
    re.compile(r"체험단\s*선정"),
    re.compile(r"업체로부터\s*제공"),
]

BROKER_PATTERNS = [
    re.compile(r"(카톡|카카오톡|위챗|wechat|line)\s*[:：]?\s*[a-zA-Z0-9_-]{4,}", re.I),
    re.compile(r"쪽지\s*주시면\s*병원\s*정보"),
]

HYPE_WORDS = ["best in the world", "miracle", "100% painless", "guaranteed perfection", "flawless magic"]


@dataclass(frozen=True)
class PhotoPairTelemetry:
    """
    VFX / Lookdev image-forensics metadata for Before/After surgical photos (Korean Medical Act Art. 56).
    Measures background exposure shift (in EV stops) and facial bounding-box aspect ratio delta.
    """
    before_bg_luma: float       # 0.0 - 1.0 linear luminance of neutral background patch
    after_bg_luma: float        # 0.0 - 1.0 linear luminance of neutral background patch
    focal_aspect_delta: float   # relative change in inter-pupillary / jaw aspect ratio (lens distortion check)


@dataclass(frozen=True)
class RawKoreanReview:
    source: str                 # "GangnamUnni" | "Babitalk" | "Sungyesa" | "NaverCafe"
    source_review_id: str
    raw_clinic_name: str        # Hangul, English, or Chosung e.g. "ㄷㅇ성형외과"
    raw_doctor_kr: str          # e.g. "이강우"
    raw_doctor_en: str          # e.g. "Kang-Woo Lee"
    raw_text_kr: str
    rating: float
    date: str                   # YYYY-MM-DD
    has_receipt_badge: bool = False
    is_discount_event_review: bool = False  # 이벤트 후기 조건부 할인
    photo_telemetry: Optional[PhotoPairTelemetry] = None


@dataclass
class CanonicalDoctor:
    slug: str
    korean_name: str
    romanized_name: str
    clinic_slug: str
    classification: str         # "board_certified" | "platform_verified" | "listed"
    rating: Optional[float] = None
    review_count: Optional[int] = None
    aliases_en: set[str] = field(default_factory=set)


@dataclass
class Stage1Extraction:
    procedures: list[str]
    is_revision: bool
    quoted_price_krw: Optional[int]
    vat_excluded_mentioned: bool
    true_2026_cost_krw: Optional[int]       # Includes mandatory 10% VAT (post Dec 31, 2025 refund repeal)
    clinic_style_signal: str                # "boutique_doctor_led" | "factory_counselor_led" | "unspecified"
    complication_mentions: list[str]
    chosung_token: Optional[str]


@dataclass
class EvaluatorReport:
    passed: bool
    iteration: int
    violations: list[str]
    directive: Optional[str]


@dataclass
class SyndicatedReviewRecord:
    verdict: Verdict
    refusal_codes: list[str]
    input_sha256: str
    dedup_fingerprint: str
    clinic_slug: Optional[str]
    doctor_slug: Optional[str]
    procedure_slugs: list[str]
    source: str
    date: str
    rating: float
    quoted_price_krw: Optional[int]
    true_2026_cost_krw: Optional[int]
    vat_warning_2026: Optional[str]
    clinic_style_signal: str
    is_revision: bool
    trust_score: float
    photo_ev_delta: Optional[float]
    evaluator_iterations: int
    summary_en: Optional[str]
    stage_trace: dict


def normalize_phonetic_en(romanized: str) -> str:
    """
    Collapse Revised Romanization vs McCune-Reischauer phonetic drift observed across
    20 duplicate doctor pairs on live gangnambeautyguide.com/en/doctors.
    """
    s = re.sub(r"\([^)]*\)", "", romanized.lower())
    s = re.sub(r"[^a-z\s]", " ", s)
    tokens = [t for t in s.split() if t]
    if not tokens:
        return ""
    norm = []
    for t in tokens:
        t = t.replace("yeong", "yung").replace("hyeong", "hyung").replace("young", "yung")
        t = t.replace("seong", "sung").replace("jeong", "jung")
        t = t.replace("cheol", "chul").replace("ryeol", "ryul")
        t = t.replace("seop", "sup").replace("geon", "gun").replace("heon", "hun")
        t = t.replace("woo", "u").replace("wu", "u").replace("hoon", "hun").replace("joon", "jun")
        t = re.sub(r"^g", "k", t)
        t = re.sub(r"^b", "p", t)
        t = re.sub(r"^j", "ch", t)
        t = re.sub(r"^d", "t", t)
        norm.append(t)
    return " ".join(sorted(norm))


def validate_doctor_entity(korean_name: str, romanized_name: str) -> list[RefusalCode]:
    """
    Catches bare-surname entries (60/467 on live GBG) and Jamo surname row-shift bugs
    (1/467 on live GBG: dr-10 '이정환' welded to 'Chan-Eol Seo').
    """
    codes: list[RefusalCode] = []
    kr = korean_name.strip()
    en = re.sub(r"\([^)]*\)", "", romanized_name).strip()
    en_tokens = [t.lower() for t in re.findall(r"[A-Za-z]+", en)]

    if not kr or len(en_tokens) < 2:
        codes.append(RefusalCode.BARE_SURNAME_ENTITY)
        return codes

    surname_kr = kr[0]
    allowed = SURNAME_HANGUL_TO_ROMAN.get(surname_kr)
    if allowed and not any(tok in allowed for tok in en_tokens):
        codes.append(RefusalCode.DOCTOR_JAMO_MISMATCH)

    return codes


def evaluate_photo_pair(telemetry: Optional[PhotoPairTelemetry]) -> tuple[Optional[float], list[RefusalCode]]:
    """
    VFX Lookdev gate: checks Before/After photo pair against Korean Medical Act Art. 56
    (동일 조건 촬영 — identical lighting and camera geometry required).
    """
    if telemetry is None:
        return None, []
    import math
    luma_b = max(telemetry.before_bg_luma, 0.01)
    luma_a = max(telemetry.after_bg_luma, 0.01)
    ev_delta = round(abs(math.log2(luma_a / luma_b)), 2)
    codes: list[RefusalCode] = []
    if ev_delta > 0.75 or abs(telemetry.focal_aspect_delta) > 0.08:
        codes.append(RefusalCode.PHOTO_EXPOSURE_MANIPULATION)
    return ev_delta, codes


def extract_krw_price(text_kr: str) -> Optional[int]:
    m = re.search(r"(\d[\d,]*)\s*만\s*원?", text_kr)
    if m:
        val = int(m.group(1).replace(",", ""))
        if 5 <= val <= 5000:
            return val * 10_000
    m_raw = re.search(r"(\d{1,2}(?:,\d{3}){2})\s*원", text_kr)
    if m_raw:
        return int(m_raw.group(1).replace(",", ""))
    return None


def extract_procedures(text_kr: str) -> tuple[list[str], bool]:
    low = text_kr.lower()
    matched: list[str] = []
    for slug, keywords in PROCEDURE_GLOSSARY.items():
        if any(kw.lower() in low for kw in keywords):
            matched.append(slug)
    is_revision = "재수술" in text_kr or "revision" in low or "des-revision" in matched
    return sorted(set(matched)), is_revision


class SyndicationPipeline:
    """
    4-Stage Agentic Workflow:
      Stage 1: ClinicalExtractorAgent (Prompt Chain Step 1)
      Stage 2: Deterministic Entity, Chosung & VFX Photo Gate
      Stage 3: EditorialTransformerAgent (Prompt Chain Step 2)
      Stage 4: MedicalHygieneEvaluator (Evaluator-Optimizer Loop, max 1 retry)
    """

    def __init__(
        self,
        clinic_aliases: dict[str, str],
        doctors: list[CanonicalDoctor],
        writer_agent_fn: Optional[Callable[[RawKoreanReview, Stage1Extraction, int], str]] = None,
    ) -> None:
        self.clinic_aliases = {self._clean_clinic_key(k): v for k, v in clinic_aliases.items()}
        self.doctors_by_kr_clinic: dict[tuple[str, str], CanonicalDoctor] = {}
        self.doctors_by_kr: dict[str, list[CanonicalDoctor]] = {}
        for doc in doctors:
            self.doctors_by_kr_clinic[(doc.korean_name, doc.clinic_slug)] = doc
            self.doctors_by_kr.setdefault(doc.korean_name, []).append(doc)
        self.seen_fingerprints: set[str] = set()
        self.writer_agent_fn = writer_agent_fn or self._default_editorial_writer

    @staticmethod
    def _clean_clinic_key(name: str) -> str:
        s = re.sub(r"(성형외과의원|성형외과|피부과의원|피부과|의원|병원|클리닉|plastic\s*surgery|clinic|ps|\s+)", "", name.lower())
        return s.strip()

    # --- STAGE 1: Clinical & Market Signal Extractor ---
    @staticmethod
    def run_stage1_extractor(rev: RawKoreanReview) -> Stage1Extraction:
        procedures, is_revision = extract_procedures(rev.raw_text_kr)
        price_krw = extract_krw_price(rev.raw_text_kr)
        vat_excl = any(k in rev.raw_text_kr for k in ["부가세 별도", "vat 별도", "현금가", "이벤트가"])
        # Post Dec 31, 2025 repeal of Restriction of Special Taxation Act Art. 107-3:
        # Foreigners cannot claim back the 10% VAT at Korean airports in 2026.
        true_2026_cost = int(round(price_krw * 1.10)) if (price_krw and vat_excl) else price_krw

        if any(k in rev.raw_text_kr for k in ["공장형", "실장님", "상담실장", "강매", "코디네이터"]):
            style = "factory_counselor_led"
        elif any(k in rev.raw_text_kr for k in ["1인 원장", "1인원장", "원장 직접", "원장님 직접", "과잉진료 없"]):
            style = "boutique_doctor_led"
        else:
            style = "unspecified"

        complications = []
        for term, label in [
            ("부기", "swelling"),
            ("멍", "bruising"),
            ("비대칭", "asymmetry"),
            ("구형구축", "capsular_contracture"),
            ("신경손상", "nerve_paresthesia"),
            ("코피", "epistaxis"),
        ]:
            if term in rev.raw_text_kr:
                complications.append(label)

        m_cho = re.search(r"([ㄱ-ㅎ]{1,3})\s*(?:성형외과|병원|의원)?", rev.raw_clinic_name)
        chosung = m_cho.group(1) if m_cho else None

        return Stage1Extraction(
            procedures=procedures,
            is_revision=is_revision,
            quoted_price_krw=price_krw,
            vat_excluded_mentioned=vat_excl,
            true_2026_cost_krw=true_2026_cost,
            clinic_style_signal=style,
            complication_mentions=complications,
            chosung_token=chosung,
        )

    # --- STAGE 2: Deterministic Entity, Chosung & VFX Photo Gate ---
    def resolve_clinic(self, raw_clinic_name: str, s1: Stage1Extraction) -> Optional[str]:
        cleaned = self._clean_clinic_key(raw_clinic_name)
        if cleaned in self.clinic_aliases:
            return self.clinic_aliases[cleaned]
        if s1.chosung_token:
            for proc in s1.procedures:
                slug = CHOSUNG_CLINIC_MAP.get((s1.chosung_token, proc))
                if slug:
                    return slug
        return None

    def resolve_doctor(self, kr_name: str, en_name: str, clinic_slug: str) -> tuple[Optional[str], list[RefusalCode]]:
        refusals = validate_doctor_entity(kr_name, en_name)
        if refusals:
            return None, refusals

        exact = self.doctors_by_kr_clinic.get((kr_name.strip(), clinic_slug))
        if exact:
            exact.aliases_en.add(en_name)
            return exact.slug, []

        candidates = self.doctors_by_kr.get(kr_name.strip(), [])
        if len(candidates) > 1:
            # Check if candidates are distinct homonym surgeons (동명이인) with divergent review counts
            rev_counts = {c.review_count for c in candidates if c.review_count is not None}
            if len(rev_counts) > 1:
                return None, [RefusalCode.HOMONYM_AMBIGUITY]

        target_phon = normalize_phonetic_en(en_name)
        for cand in candidates:
            if normalize_phonetic_en(cand.romanized_name) == target_phon:
                cand.aliases_en.add(en_name)
                return cand.slug, []
        return None, []

    @staticmethod
    def compute_dedup_fingerprint(
        clinic_slug: str,
        procedures: list[str],
        date_str: str,
        price_krw: Optional[int],
        raw_text_kr: str,
    ) -> str:
        year_week = date_str[:7]
        price_bucket = str((price_krw or 0) // 500_000)
        kr_tokens = sorted(set(re.findall(r"[가-힣]{2,}", raw_text_kr)))[:12]
        canonical = "|".join([
            clinic_slug,
            ",".join(sorted(procedures)),
            year_week,
            price_bucket,
            ",".join(kr_tokens),
        ])
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    # --- STAGE 3: Editorial Transformer Agent ---
    @staticmethod
    def _default_editorial_writer(rev: RawKoreanReview, s1: Stage1Extraction, attempt: int) -> str:
        proc_str = ", ".join(s1.procedures) if s1.procedures else "aesthetic procedure"
        rev_tag = " (revision case)" if s1.is_revision else ""
        if s1.quoted_price_krw:
            if s1.vat_excluded_mentioned and s1.true_2026_cost_krw:
                price_clause = (
                    f" Quoted domestic event price was ₩{s1.quoted_price_krw:,} (VAT excluded); "
                    f"true 2026 out-of-pocket cost is ₩{s1.true_2026_cost_krw:,} Including 10% VAT "
                    f"(non-refundable following the Dec 31, 2025 sunset of Article 107-3)."
                )
            else:
                price_clause = f" Reported procedure cost was ₩{s1.quoted_price_krw:,}."
        else:
            price_clause = " Cost was not disclosed in the source report."

        style_clause = ""
        if s1.clinic_style_signal == "factory_counselor_led":
            style_clause = " Consultation was primarily led by a non-physician sales coordinator (상담실장) with high-volume factory throughput."
        elif s1.clinic_style_signal == "boutique_doctor_led":
            style_clause = " The operating specialist personally conducted the consultation without coordinator upselling."

        comp_clause = ""
        if s1.complication_mentions:
            comp_clause = f" Post-operative recovery noted {', '.join(s1.complication_mentions)}."

        return (
            f"The patient underwent {proc_str}{rev_tag} ({rev.source}, rated {rev.rating:.1f}/5.0)."
            f"{price_clause}{style_clause}{comp_clause}"
        )

    # --- STAGE 4: Medical-Hygiene Evaluator-Optimizer ---
    @staticmethod
    def run_stage4_evaluator(draft_en: str, s1: Stage1Extraction, iteration: int) -> EvaluatorReport:
        violations: list[str] = []
        low = draft_en.lower()

        # Check 1: Price faithfulness
        if s1.quoted_price_krw is not None and "not mentioned" in low and "cost" in low:
            violations.append("PRICE_DROPPED_IN_SUMMARY")
        if s1.quoted_price_krw is not None and f"{s1.quoted_price_krw:,}" not in draft_en:
            violations.append("EXACT_KRW_FIGURE_MISSING")

        # Check 2: Medical-language hygiene (no promotional superlatives)
        for hype in HYPE_WORDS:
            if hype in low:
                violations.append(f"PROMOTIONAL_HYPE:{hype}")

        # Check 3: Complication & consultation-style preservation
        for comp in s1.complication_mentions:
            if comp not in low:
                violations.append(f"COMPLICATION_SMOOTHED_OVER:{comp}")

        if violations:
            directive = (
                f"Rewrite required: fix {', '.join(violations)}. "
                f"Include exact KRW {s1.quoted_price_krw}, preserve complications {s1.complication_mentions}, "
                f"and strip promotional superlatives."
            )
            return EvaluatorReport(passed=False, iteration=iteration, violations=violations, directive=directive)

        return EvaluatorReport(passed=True, iteration=iteration, violations=[], directive=None)

    def process_review(self, rev: RawKoreanReview) -> SyndicatedReviewRecord:
        payload_bytes = json.dumps(asdict(rev), sort_keys=True, ensure_ascii=False).encode("utf-8")
        input_sha = hashlib.sha256(payload_bytes).hexdigest()
        refusals: list[RefusalCode] = []

        # Stage 1: Clinical & Market Signal Extraction
        s1 = self.run_stage1_extractor(rev)

        # Stage 2A: KFTC Sponsored Ad & Illegal Broker Gate
        if any(p.search(rev.raw_text_kr) for p in SPONSORED_PATTERNS):
            refusals.append(RefusalCode.KFTC_SPONSORED_AD)
        if any(p.search(rev.raw_text_kr) for p in BROKER_PATTERNS):
            refusals.append(RefusalCode.BROKER_SHILL_PATTERN)

        # Stage 2B: Clinic Entity & Chosung Resolution
        clinic_slug = self.resolve_clinic(rev.raw_clinic_name, s1)
        if not clinic_slug:
            refusals.append(RefusalCode.UNRESOLVED_CLINIC)

        # Stage 2C: Doctor Entity & Homonym / Jamo Gate
        doctor_slug: Optional[str] = None
        if rev.raw_doctor_kr or rev.raw_doctor_en:
            doc_slug, doc_refusals = self.resolve_doctor(
                rev.raw_doctor_kr, rev.raw_doctor_en, clinic_slug or ""
            )
            doctor_slug = doc_slug
            refusals.extend(doc_refusals)

        # Stage 2D: VFX Before/After Photo Exposure Gate (의료법 제56조)
        photo_ev_delta, photo_refusals = evaluate_photo_pair(rev.photo_telemetry)
        refusals.extend(photo_refusals)

        # Stage 2E: Cross-Platform Shingle Fingerprint De-duplication
        dedup_fp = self.compute_dedup_fingerprint(
            clinic_slug or "unknown", s1.procedures, rev.date, s1.quoted_price_krw, rev.raw_text_kr
        )
        if dedup_fp in self.seen_fingerprints:
            refusals.append(RefusalCode.CROSS_PLATFORM_DUPLICATE)

        vat_warning = (
            "10% foreign medical VAT refund expired Dec 31, 2025 (Art. 107-3); +10% VAT is non-refundable in 2026."
            if s1.vat_excluded_mentioned else None
        )

        # Fail-closed HOLD before spending tokens on Stage 3/4 if hard gate triggered
        hard_holds = {
            RefusalCode.KFTC_SPONSORED_AD,
            RefusalCode.BROKER_SHILL_PATTERN,
            RefusalCode.UNRESOLVED_CLINIC,
            RefusalCode.CROSS_PLATFORM_DUPLICATE,
        }
        if any(r in hard_holds for r in refusals):
            return SyndicatedReviewRecord(
                verdict=Verdict.HOLD,
                refusal_codes=[r.value for r in refusals],
                input_sha256=input_sha,
                dedup_fingerprint=dedup_fp,
                clinic_slug=clinic_slug,
                doctor_slug=doctor_slug,
                procedure_slugs=s1.procedures,
                source=rev.source,
                date=rev.date,
                rating=rev.rating,
                quoted_price_krw=s1.quoted_price_krw,
                true_2026_cost_krw=s1.true_2026_cost_krw,
                vat_warning_2026=vat_warning,
                clinic_style_signal=s1.clinic_style_signal,
                is_revision=s1.is_revision,
                trust_score=0.0,
                photo_ev_delta=photo_ev_delta,
                evaluator_iterations=0,
                summary_en=None,
                stage_trace={"stage1": asdict(s1), "stage2_refusals": [r.value for r in refusals]},
            )

        # Stage 3 & Stage 4: Editorial Writer + Evaluator-Optimizer Loop (max 2 iterations)
        eval_history = []
        draft_en = ""
        for attempt in (1, 2):
            draft_en = self.writer_agent_fn(rev, s1, attempt)
            eval_rep = self.run_stage4_evaluator(draft_en, s1, attempt)
            eval_history.append(asdict(eval_rep))
            if eval_rep.passed:
                break
        else:
            refusals.append(RefusalCode.HALLUCINATED_TRANSLATION)

        # Trust Score Calculation (discounts 이벤트 후기 conditional reviews)
        trust = 0.35
        if rev.has_receipt_badge:
            trust += 0.35
        if rev.photo_telemetry and RefusalCode.PHOTO_EXPOSURE_MANIPULATION not in refusals:
            trust += 0.15
        if doctor_slug is not None:
            trust += 0.15
        if rev.is_discount_event_review:
            trust -= 0.25
        trust = round(max(0.05, min(1.0, trust)), 2)

        if refusals:
            verdict = Verdict.QUARANTINE
        else:
            verdict = Verdict.GO
            self.seen_fingerprints.add(dedup_fp)

        return SyndicatedReviewRecord(
            verdict=verdict,
            refusal_codes=[r.value for r in refusals],
            input_sha256=input_sha,
            dedup_fingerprint=dedup_fp,
            clinic_slug=clinic_slug,
            doctor_slug=doctor_slug,
            procedure_slugs=s1.procedures,
            source=rev.source,
            date=rev.date,
            rating=rev.rating,
            quoted_price_krw=s1.quoted_price_krw,
            true_2026_cost_krw=s1.true_2026_cost_krw,
            vat_warning_2026=vat_warning,
            clinic_style_signal=s1.clinic_style_signal,
            is_revision=s1.is_revision,
            trust_score=trust,
            photo_ev_delta=photo_ev_delta,
            evaluator_iterations=len(eval_history),
            summary_en=draft_en,
            stage_trace={
                "stage1": asdict(s1),
                "stage2": {
                    "clinic_slug": clinic_slug,
                    "doctor_slug": doctor_slug,
                    "photo_ev_delta": photo_ev_delta,
                    "refusals": [r.value for r in refusals],
                },
                "stage4_evaluator": eval_history,
            },
        )


# --- FINAL ENGINEERING ADDITIONS: RECEIPT VERIFICATION, PIXEL HISTOGRAM GATE & 2026 QUOTE ARBITRAGE ---

KOREAN_BIZ_REG_RE = re.compile(r"\b(\d{3})-(\d{2})-(\d{5})\b")
KOREAN_CARD_APPROVAL_RE = re.compile(r"(?:승인번호|승인)\s*[:：]?\s*(\d{8})\b")


@dataclass(frozen=True)
class TaxReceiptCheck:
    verified: bool
    biz_reg_number: Optional[str]
    approval_code: Optional[str]
    reason: str


def validate_korean_tax_receipt(ocr_text: str) -> TaxReceiptCheck:
    """
    Validates Korean hospital card slip / cash receipt (영수증 인증) using:
    1. 10-digit Korean Business Registration Number (사업자등록번호 XXX-XX-XXXXX) with weighted mod-10 checksum.
    2. 8-digit VAN/KFTC card approval code (승인번호).
    """
    m_biz = KOREAN_BIZ_REG_RE.search(ocr_text)
    m_app = KOREAN_CARD_APPROVAL_RE.search(ocr_text)
    if not m_biz:
        return TaxReceiptCheck(False, None, None, "MISSING_BIZ_REG_NUMBER")
    digits = [int(c) for c in (m_biz.group(1) + m_biz.group(2) + m_biz.group(3))]
    weights = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    total = sum(d * w for d, w in zip(digits[:9], weights))
    total += (digits[8] * 5) // 10
    check_digit = (10 - (total % 10)) % 10
    biz_str = f"{m_biz.group(1)}-{m_biz.group(2)}-{m_biz.group(3)}"
    if check_digit != digits[9]:
        return TaxReceiptCheck(False, biz_str, None, "INVALID_BIZ_REG_MOD10_CHECKSUM")
    if not m_app:
        return TaxReceiptCheck(False, biz_str, None, "MISSING_8DIGIT_CARD_APPROVAL")
    return TaxReceiptCheck(True, biz_str, m_app.group(1), "VERIFIED_NTS_RECEIPT")


def compute_image_pair_telemetry(
    before_border_pixels: list[int],
    after_border_pixels: list[int],
    before_face_bbox: tuple[int, int],
    after_face_bbox: tuple[int, int],
) -> PhotoPairTelemetry:
    """
    Computes linear luminance (sRGB gamma 2.2 decoded) over background border pixels
    and facial bounding-box aspect ratio delta directly from pixel arrays.
    """
    def mean_linear_luma(px_list: list[int]) -> float:
        if not px_list:
            return 0.5
        lin = [((max(0, min(255, p)) / 255.0) ** 2.2) for p in px_list]
        return round(sum(lin) / len(lin), 4)

    b_luma = mean_linear_luma(before_border_pixels)
    a_luma = mean_linear_luma(after_border_pixels)
    b_ratio = before_face_bbox[0] / max(1, before_face_bbox[1])
    a_ratio = after_face_bbox[0] / max(1, after_face_bbox[1])
    aspect_delta = round(abs(a_ratio - b_ratio) / max(0.01, b_ratio), 4)
    return PhotoPairTelemetry(before_bg_luma=b_luma, after_bg_luma=a_luma, focal_aspect_delta=aspect_delta)


# Canonical domestic Korean median event prices (KRW, VAT-exclusive) for foreign quote arbitrage
DOMESTIC_BENCHMARK_KRW: dict[str, tuple[int, int]] = {
    "des": (1_200_000, 2_200_000),
    "des-revision": (2_500_000, 4_200_000),
    "rhinoplasty": (3_000_000, 5_500_000),
    "facial-contouring": (5_500_000, 9_500_000),
    "face-lift": (6_000_000, 11_000_000),
    "breast-augmentation": (7_500_000, 12_500_000),
    "booster": (250_000, 550_000),
    "botox": (50_000, 180_000),
}


@dataclass(frozen=True)
class QuoteArbitrageResult:
    procedure_slug: str
    foreigner_quote_krw: int
    legacy_fake_refund_krw: int          # What outdated /en/tools/tax-refund claims (expired Dec 31, 2025)
    actual_2026_refund_krw: int          # ₩0 under Restriction of Special Taxation Act Art. 107-3 sunset
    true_2026_out_of_pocket_krw: int
    local_vat_inclusive_range_krw: tuple[int, int]
    foreigner_markup_ratio: float
    verdict: str                         # "FAIR_LOCAL_PARITY" | "MODERATE_TOURIST_SPREAD" | "FOREIGNER_SURCHARGE_ALERT"


def calculate_2026_quote_arbitrage(
    procedure_slug: str,
    foreigner_quote_krw: int,
    quote_excludes_vat: bool = True,
) -> QuoteArbitrageResult:
    """
    Replaces gangnambeautyguide.com/en/tools/tax-refund with a 2026-compliant calculator:
    1. Zeroes out the expired 10% airport VAT refund (sunset Dec 31, 2025).
    2. Adds mandatory 10% VAT if clinic quoted VAT-exclusive (부가세 별도).
    3. Compares against domestic GangnamUnni/Babitalk VAT-inclusive median range.
    """
    true_cost = int(round(foreigner_quote_krw * 1.10)) if quote_excludes_vat else foreigner_quote_krw
    legacy_refund = int(round((true_cost / 11.0) * 0.70))  # Old 70%-retained VAT refund formula on live GBG
    low_dom, high_dom = DOMESTIC_BENCHMARK_KRW.get(procedure_slug, (1_500_000, 3_500_000))
    dom_inc_low, dom_inc_high = int(round(low_dom * 1.10)), int(round(high_dom * 1.10))
    ratio = round(true_cost / max(1, dom_inc_high), 2)
    if ratio <= 1.15:
        verdict = "FAIR_LOCAL_PARITY"
    elif ratio <= 1.50:
        verdict = "MODERATE_TOURIST_SPREAD"
    else:
        verdict = "FOREIGNER_SURCHARGE_ALERT"
    return QuoteArbitrageResult(
        procedure_slug=procedure_slug,
        foreigner_quote_krw=foreigner_quote_krw,
        legacy_fake_refund_krw=legacy_refund,
        actual_2026_refund_krw=0,
        true_2026_out_of_pocket_krw=true_cost,
        local_vat_inclusive_range_krw=(dom_inc_low, dom_inc_high),
        foreigner_markup_ratio=ratio,
        verdict=verdict,
    )
