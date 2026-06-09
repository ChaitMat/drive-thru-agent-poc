from drive_thru.tools import query_menu


def test_returns_all_when_no_filter():
    results = query_menu()
    kinds = {r["kind"] for r in results}
    assert kinds == {"item", "combo"}
    assert len(results) > 40


def test_filters_by_category_burger():
    results = query_menu(category="burger")
    assert all(r["kind"] == "item" and r["category"] == "burger" for r in results)
    names = {r["name"] for r in results}
    assert "Aloo Tikki Burger" in names
    assert "Chicken Maharaja Burger" in names


def test_combo_category_returns_only_combos():
    results = query_menu(category="combo")
    assert results
    assert all(r["kind"] == "combo" for r in results)


def test_is_veg_filter_excludes_non_veg():
    results = query_menu(is_veg=True)
    assert all(r["is_veg"] is True for r in results)
    names = {r["name"] for r in results}
    assert "Chicken Maharaja Burger" not in names
    assert "Aloo Tikki Burger" in names


def test_is_veg_false_returns_only_non_veg():
    results = query_menu(is_veg=False)
    assert results
    assert all(r["is_veg"] is False for r in results)


def test_name_contains_case_insensitive():
    results = query_menu(name_contains="MAHARAJA")
    names = {r["name"] for r in results}
    assert "Chicken Maharaja Burger" in names
    assert "Maharaja Combo" in names


def test_max_price_caps_results():
    results = query_menu(category="burger", max_price_paise=10000)
    assert results
    assert all(r["price_paise"] <= 10000 for r in results)
