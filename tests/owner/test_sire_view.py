"""種牡馬分析の表示（owner/sire_view.py）のうち、集計範囲の注記。"""

from keiba_analysis.owner import sire_view as sv
from keiba_analysis.shared.sire_runs import Coverage


def test_local_scope_defaults_to_the_whole_db():
    assert sv.local_scope() == "1995年以降のJRA"
    assert sv.LOCAL_SCOPE == sv.local_scope()


def test_local_scope_follows_since():
    assert sv.local_scope("2023-01-01") == "2023年以降のJRA"
    assert "2023年以降のJRA" in sv.local_note("2023-01-01")


def test_render_coverage_takes_the_scope():
    coverage = Coverage(sire_horses=3, sire_runs=7, known=10, total=10)
    assert "（2023年以降のJRA）" in sv.render_coverage(coverage, sv.local_scope("2023-01-01"))
    assert "（1995年以降のJRA）" in sv.render_coverage(coverage)
