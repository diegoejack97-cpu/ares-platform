from ares.impact.export import csv_cell, render_report


def test_export_preserves_missing_values_and_escapes_formula():
    summary = {
        "source": "synthetic",
        "window": {"since": "2026-09-01", "until": "2026-09-15"},
        "definitions": ["Influência não prova causalidade"],
        "amounts": [
            {
                "currency": "BRL",
                "sale_value": 100,
                "ares_influenced_value": 50,
                "incremental_value": None,
            }
        ],
    }
    rows = [{"intervention_id": "test", "attribution_method": "=1+1", "incremental_value": None}]
    csv = render_report(summary, rows, "csv").decode("utf-8-sig")
    assert "'=1+1" in csv
    assert "None" not in csv
    assert csv_cell("@SUM(A1)").startswith("'")
    assert render_report(summary, rows, "pdf").startswith(b"%PDF-")
