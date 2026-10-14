from pipeline.summary_review import anchors, context_for, sha


def test_anchors_cover_dates_codes_and_decimal_variants():
    a = anchors("EUR 0.45 per kg; entry B3011 from 21 November 2026; NACE C22; 15% by 2032; Regulation (EU) 2024/1157")
    for tok in ["21 November 2026", "21. November 2026", "B3011", "C22", "0.45", "0,45", "15 %", "2024/1157"]:
        assert tok in a


def test_context_includes_far_away_anchor_and_verified_quote():
    filler = "Recital text without the facts. " * 5000
    text = "TITLE OF THE ACT\n" + filler + "plastic waste classified under entry B3011" + filler + "It shall apply from 21 May 2026." + filler
    ctx = context_for(text, "The ban on entry B3011 exports", budget=20000, extra=["It shall apply from 21 May 2026."])
    assert "TITLE OF THE ACT" in ctx and "B3011" in ctx and "21 May 2026" in ctx
    assert len(ctx) <= 20000 + 200


def test_edit_changes_hash():
    assert sha("A summary.") == sha("A summary.  ") != sha("A summary, edited.")
