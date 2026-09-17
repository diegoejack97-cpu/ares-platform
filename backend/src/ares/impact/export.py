import csv
from io import BytesIO, StringIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.styles import getSampleStyleSheet  # type: ignore[import-untyped]
from reportlab.platypus import (  # type: ignore[import-untyped]
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else text


def render_report(summary: dict[str, Any], rows: list[dict[str, Any]], format: str) -> bytes:
    synthetic = any(amount.get("synthetic_observations", 0) for amount in summary["amounts"])
    notice = "Dados sintéticos de demonstração; não representam resultados comerciais reais."
    fields = [
        "intervention_id",
        "opportunity_id",
        "correlation_id",
        "status",
        "created_at",
        "state_before_ref",
        "state_after_ref",
        "result_type",
        "sale_value",
        "ares_influenced_value",
        "incremental_value",
        "currency",
        "attribution_level",
        "attribution_method",
        "observed_at",
    ]
    if format == "csv":
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["ARES Impacto", "source", summary["source"]])
        if synthetic:
            writer.writerow(["aviso", notice])
        writer.writerow(
            ["periodo", str(summary["window"]["since"]), str(summary["window"]["until"])]
        )
        for definition in summary["definitions"]:
            writer.writerow(["definicao", definition])
        writer.writerow(fields)
        for row in rows:
            writer.writerow([csv_cell(row.get(field)) for field in fields])
        return output.getvalue().encode("utf-8-sig")
    buffer = BytesIO()
    styles = getSampleStyleSheet()
    story: list[Any] = [
        Paragraph("ARES / Impacto", styles["Title"]),
        Paragraph(escape(summary["source"]), styles["Normal"]),
        Paragraph(
            escape(f"Período: {summary['window']['since']} a {summary['window']['until']}"),
            styles["Normal"],
        ),
        Spacer(1, 16),
    ]
    for definition in summary["definitions"]:
        story.extend([Paragraph(escape(definition), styles["Normal"]), Spacer(1, 6)])
    if synthetic:
        story.append(Paragraph(notice, styles["Heading2"]))
    story.append(Spacer(1, 12))
    data = [["Moeda", "Vendido", "Influenciado", "Incremental"]]
    for amount in summary["amounts"]:
        data.append(
            [amount["currency"] or "Não informada"]
            + [
                str(amount[field])
                if amount[field] is not None
                else "Não comprovado"
                if field == "incremental_value"
                else "Não informado"
                for field in ["sale_value", "ares_influenced_value", "incremental_value"]
            ]
        )
    table = Table(data, colWidths=[80, 120, 120, 140], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#263638")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("PADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.extend([table, Spacer(1, 20), Paragraph("Intervenções e evidências", styles["Heading2"])])
    for row in rows:
        text = "<br/>".join(
            f"<b>{field}</b>: "
            + escape(str(row.get(field) if row.get(field) is not None else "Não informado"))
            for field in fields
        )
        story.extend([Paragraph(text, styles["Normal"]), Spacer(1, 14)])
    SimpleDocTemplate(
        buffer, title="ARES Impacto", author="ARES", leftMargin=42, rightMargin=42
    ).build(story)
    return buffer.getvalue()
