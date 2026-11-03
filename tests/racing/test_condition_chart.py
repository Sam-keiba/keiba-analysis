from keiba_analysis.racing.condition_chart import build_metric_bar_spec

ROWS = [{"label": "東京", "value": 80.0, "note": "80.0%", "thin": False, "detail": "10走"}]


def test_keeps_the_given_order_and_has_no_reference_by_default():
    spec = build_metric_bar_spec(ROWS, "勝率（％）")
    assert spec["layer"][0]["encoding"]["y"]["sort"] == ["東京"]
    assert len(spec["layer"]) == 2


def test_reference_line_for_return_rate():
    spec = build_metric_bar_spec(ROWS, "回収率（％）", reference=100)
    assert spec["layer"][-1]["mark"]["type"] == "rule"
    assert spec["layer"][-1]["data"]["values"] == [{"reference": 100}]
