import pytest
from gbg_pipeline import (
    CanonicalDoctor,
    PhotoPairTelemetry,
    RawKoreanReview,
    RefusalCode,
    SyndicationPipeline,
    Verdict,
    validate_doctor_entity,
)


def make_pipeline() -> SyndicationPipeline:
    clinics = {
        "디에이성형외과": "da-ps",
        "DA Plastic Surgery": "da-ps",
        "나나성형외과": "nana-ps",
        "뷰성형외과": "view-ps",
    }
    doctors = [
        CanonicalDoctor(
            slug="dr-60",
            korean_name="이강우",
            romanized_name="Gang-Woo Lee",
            clinic_slug="da-ps",
            classification="board_certified",
            rating=4.6,
            review_count=999,
        ),
        CanonicalDoctor(
            slug="dr-11",
            korean_name="이정환",
            romanized_name="Jung-Hwan Lee",
            clinic_slug="view-ps",
            classification="listed",
            rating=4.7,
            review_count=118,
        ),
        # Homonym pair (동명이인) from live GBG: 김형준 dr-92 (132 reviews) vs dr-65 (939 reviews)
        CanonicalDoctor(
            slug="dr-92",
            korean_name="김형준",
            romanized_name="Hyung-Joon Kim",
            clinic_slug="nana-ps",
            classification="board_certified",
            rating=4.85,
            review_count=132,
        ),
        CanonicalDoctor(
            slug="dr-65",
            korean_name="김형준",
            romanized_name="Hyung-Jun Kim",
            clinic_slug="other-ps",
            classification="board_certified",
            rating=4.55,
            review_count=939,
        ),
    ]
    return SyndicationPipeline(clinic_aliases=clinics, doctors=doctors)


def test_romanization_drift_and_2026_vat_math():
    """Merges Kang-Woo Lee -> dr-60 (Gang-Woo Lee) and computes 2026 non-refundable 10% VAT."""
    pipe = make_pipeline()
    rev = RawKoreanReview(
        source="Babitalk",
        source_review_id="bt-101",
        raw_clinic_name="디에이성형외과의원",
        raw_doctor_kr="이강우",
        raw_doctor_en="Kang-Woo Lee",
        raw_text_kr="1인 원장님 직접 상담이라 좋았어요. 자연유착 쌍수 이벤트가 200만원 부가세 별도로 진행했고 부기 적어요.",
        rating=5.0,
        date="2026-04-13",
        has_receipt_badge=True,
        photo_telemetry=PhotoPairTelemetry(before_bg_luma=0.42, after_bg_luma=0.44, focal_aspect_delta=0.01),
    )
    out = pipe.process_review(rev)
    assert out.verdict == Verdict.GO
    assert out.clinic_slug == "da-ps"
    assert out.doctor_slug == "dr-60"
    assert out.quoted_price_krw == 2_000_000
    assert out.true_2026_cost_krw == 2_200_000
    assert out.clinic_style_signal == "boutique_doctor_led"
    assert out.trust_score == 1.0


def test_sungyesa_chosung_masked_negative_review_decoded():
    """Decodes initial-masked (초성) 'ㄷㅇ성형외과' + facelift context -> 'da-ps' and captures factory counselor signal."""
    pipe = make_pipeline()
    rev = RawKoreanReview(
        source="Sungyesa",
        source_review_id="sy-404",
        raw_clinic_name="ㄷㅇ성형외과",
        raw_doctor_kr="",
        raw_doctor_en="",
        raw_text_kr="공장형이라 상담실장님이 과하게 추천함. 안면거상 800만원에 했는데 부기랑 비대칭이 아직 있어요.",
        rating=2.5,
        date="2026-04-13",
        has_receipt_badge=True,
    )
    out = pipe.process_review(rev)
    assert out.verdict == Verdict.GO
    assert out.clinic_slug == "da-ps"
    assert out.clinic_style_signal == "factory_counselor_led"
    assert "asymmetry" in out.summary_en


def test_vfx_before_after_photo_exposure_gate_quarantines_manipulated_pair():
    """Catches >0.75 EV studio background lighting boost between Before and After photos (의료법 제56조)."""
    pipe = make_pipeline()
    rev = RawKoreanReview(
        source="GangnamUnni",
        source_review_id="gu-77",
        raw_clinic_name="나나성형외과",
        raw_doctor_kr="",
        raw_doctor_en="",
        raw_text_kr="코성형 자가늑 450만원 후기입니다.",
        rating=5.0,
        date="2026-04-13",
        photo_telemetry=PhotoPairTelemetry(before_bg_luma=0.25, after_bg_luma=0.66, focal_aspect_delta=0.02),
    )
    out = pipe.process_review(rev)
    assert out.verdict == Verdict.QUARANTINE
    assert RefusalCode.PHOTO_EXPOSURE_MANIPULATION.value in out.refusal_codes
    assert out.photo_ev_delta == 1.4


def test_homonym_surgeons_not_falsely_merged_without_clinic_match():
    """Protects Korean homonym surgeons (동명이인: 김형준 dr-92 vs dr-65) when clinic does not disambiguate."""
    pipe = make_pipeline()
    rev = RawKoreanReview(
        source="GangnamUnni",
        source_review_id="gu-88",
        raw_clinic_name="뷰성형외과",
        raw_doctor_kr="김형준",
        raw_doctor_en="Hyung-Jun Kim",
        raw_text_kr="쌍수 180만원에 했어요.",
        rating=4.5,
        date="2026-04-13",
    )
    out = pipe.process_review(rev)
    assert out.verdict == Verdict.QUARANTINE
    assert RefusalCode.HOMONYM_AMBIGUITY.value in out.refusal_codes


def test_jamo_surname_mismatch_and_bare_surname_caught():
    """Reproduces live GBG bugs dr-10 ('이정환' != 'Chan-Eol Seo') and dr-131 ('Creamy')."""
    assert RefusalCode.DOCTOR_JAMO_MISMATCH in validate_doctor_entity("이정환", "Chan-Eol Seo")
    assert RefusalCode.BARE_SURNAME_ENTITY in validate_doctor_entity("", "Creamy")


def test_kftc_sponsored_ad_and_broker_shill_fail_closed():
    pipe = make_pipeline()
    ad_rev = RawKoreanReview(
        source="NaverCafe",
        source_review_id="nc-99",
        raw_clinic_name="나나성형외과",
        raw_doctor_kr="",
        raw_doctor_en="",
        raw_text_kr="코성형 후기입니다. 소정의 원고료를 제공받아 작성되었습니다. 카톡: beautybroker88",
        rating=5.0,
        date="2026-04-13",
    )
    out = pipe.process_review(ad_rev)
    assert out.verdict == Verdict.HOLD
    assert RefusalCode.KFTC_SPONSORED_AD.value in out.refusal_codes
    assert RefusalCode.BROKER_SHILL_PATTERN.value in out.refusal_codes


def test_cross_platform_syndicated_duplicate_blocked():
    pipe = make_pipeline()
    r1 = RawKoreanReview(
        source="GangnamUnni",
        source_review_id="gu-1",
        raw_clinic_name="디에이성형외과",
        raw_doctor_kr="이강우",
        raw_doctor_en="Gang-Woo Lee",
        raw_text_kr="안면윤곽 사각턱 광대축소 수술 650만원에 했어요 만족합니다",
        rating=5.0,
        date="2026-04-12",
    )
    r2 = RawKoreanReview(
        source="Babitalk",
        source_review_id="bt-882",
        raw_clinic_name="DA Plastic Surgery",
        raw_doctor_kr="이강우",
        raw_doctor_en="Kang-Woo Lee",
        raw_text_kr="사각턱 광대축소 안면윤곽 수술 650만원에 했어요! 만족합니다~",
        rating=5.0,
        date="2026-04-13",
    )
    assert pipe.process_review(r1).verdict == Verdict.GO
    second = pipe.process_review(r2)
    assert second.verdict == Verdict.HOLD
    assert RefusalCode.CROSS_PLATFORM_DUPLICATE.value in second.refusal_codes


def test_evaluator_optimizer_loop_retries_and_fixes_bad_first_draft():
    """Proves Stage 4 Evaluator catches hype/dropped price on attempt 1 and converges on attempt 2."""
    def flaky_writer(rev, s1, attempt):
        if attempt == 1:
            return "The patient had a miracle eyelid surgery. Cost was not mentioned."
        return SyndicationPipeline._default_editorial_writer(rev, s1, attempt)

    pipe = make_pipeline()
    pipe.writer_agent_fn = flaky_writer
    rev = RawKoreanReview(
        source="GangnamUnni",
        source_review_id="gu-55",
        raw_clinic_name="뷰성형외과",
        raw_doctor_kr="이정환",
        raw_doctor_en="Jung-Hwan Lee",
        raw_text_kr="절개 눈재수술 350만원에 받았어요. 부기 있었음.",
        rating=4.0,
        date="2026-04-13",
    )
    out = pipe.process_review(rev)
    assert out.verdict == Verdict.GO
    assert out.evaluator_iterations == 2
    assert out.stage_trace["stage4_evaluator"][0]["passed"] is False
    assert out.stage_trace["stage4_evaluator"][1]["passed"] is True


def test_korean_tax_receipt_mod10_checksum_and_approval_code():
    """Verifies Korean Business Registration Number (사업자등록번호) mod-10 checksum and 8-digit VAN approval code."""
    from gbg_pipeline import validate_korean_tax_receipt
    # 211-88-49289 -> valid mod-10 checksum
    valid_ocr = "디에이성형외과의원 사업자등록번호: 211-88-49289 결제금액 2,200,000원 승인번호: 48291034"
    res = validate_korean_tax_receipt(valid_ocr)
    assert res.verified is True
    assert res.biz_reg_number == "211-88-49289"
    assert res.approval_code == "48291034"

    # Tampered last digit (211-88-49281) must fail mod-10 checksum
    bad_ocr = "사업자등록번호: 211-88-49281 승인번호: 48291034"
    bad_res = validate_korean_tax_receipt(bad_ocr)
    assert bad_res.verified is False
    assert bad_res.reason == "INVALID_BIZ_REG_MOD10_CHECKSUM"


def test_pixel_array_to_photo_telemetry_catches_exposure_shift():
    """Computes sRGB gamma-decoded linear luminance directly from pixel arrays and flags studio boost."""
    from gbg_pipeline import compute_image_pair_telemetry, evaluate_photo_pair, RefusalCode
    tel = compute_image_pair_telemetry(
        before_border_pixels=[120, 122, 118, 121],
        after_border_pixels=[205, 210, 208, 207],
        before_face_bbox=(400, 500),
        after_face_bbox=(402, 500),
    )
    ev_delta, codes = evaluate_photo_pair(tel)
    assert ev_delta > 1.5
    assert RefusalCode.PHOTO_EXPOSURE_MANIPULATION in codes


def test_2026_quote_arbitrage_replaces_expired_vat_refund():
    """Replaces outdated /en/tools/tax-refund (sunset Dec 31, 2025 under Art. 107-3) and flags foreigner surcharge."""
    from gbg_pipeline import calculate_2026_quote_arbitrage
    arb = calculate_2026_quote_arbitrage("des", foreigner_quote_krw=4_500_000, quote_excludes_vat=True)
    assert arb.actual_2026_refund_krw == 0
    assert arb.legacy_fake_refund_krw > 300_000
    assert arb.true_2026_out_of_pocket_krw == 4_950_000
    assert arb.verdict == "FOREIGNER_SURCHARGE_ALERT"


def test_nextjs_redirect_map_covers_all_21_duplicate_doctors():
    """Verifies drop-in Next.js 301 redirect rules generated for all 21 spelling-twin doctor duplicates."""
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).parent / "data" / "nextjs_redirects_21.json").read_text(encoding="utf-8"))
    assert data["count"] == 21
    assert any(r["source"] == "/:locale/doctors/dr-136" and r["destination"] == "/:locale/doctors/dr-60" for r in data["nextjs_redirects"])
