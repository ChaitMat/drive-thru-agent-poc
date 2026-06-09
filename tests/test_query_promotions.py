from drive_thru.tools import query_promotions


def test_returns_seeded_promotions():
    promos = query_promotions()
    names = {p["name"] for p in promos}
    assert "Highway Happy Hour" in names
    assert "Maharaja Monday" in names
    assert len(promos) >= 6


def test_each_promo_has_valid_discount_type():
    valid_types = {"percent", "flat_paise", "combo_price_paise"}
    for promo in query_promotions():
        assert promo["discount_type"] in valid_types
        assert promo["discount_value"] > 0
