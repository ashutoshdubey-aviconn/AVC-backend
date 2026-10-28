"""Build the MQTT flow documentation from flows.py.

    python docs/mqtt-flows/generate.py

Writes one draw.io diagram per flow (docs/mqtt-flows/drawio/*.drawio, open in
https://app.diagrams.net or the draw.io desktop app) and docs/mqtt-flows/README.md
(the same flows as Mermaid charts, which GitHub renders, plus the details).
Edit flows.py, not the generated files.
"""

import html
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from flows import FLOWS, INTRO  # noqa: E402

COL_W, ROW_H = 250, 105
NODE_W, NODE_H = 210, 64
MARGIN_X, MARGIN_Y = 40, 110

STYLES = {
    "start": "ellipse;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;fontStyle=1;",
    "end": "ellipse;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;",
    "process": "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;",
    "decision": "rhombus;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;",
    "db": "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;size=10;fillColor=#d5e8d4;strokeColor=#82b366;",
    "queue": "shape=parallelogram;perimeter=parallelogramPerimeter;whiteSpace=wrap;html=1;fixedSize=1;fillColor=#e1d5e7;strokeColor=#9673a6;",
    "alarm": "rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;",
    "ext": "rounded=0;whiteSpace=wrap;html=1;dashed=1;fillColor=#ffffff;strokeColor=#666666;",
    "skip": "rounded=1;whiteSpace=wrap;html=1;fillColor=#eeeeee;strokeColor=#999999;fontColor=#555555;",
}
LEGEND = [
    ("process", "Processing step"), ("decision", "Decision"), ("db", "Database table"),
    ("queue", "RabbitMQ queue / MQTT topic"), ("alarm", "Alarm / e-mail"),
    ("ext", "External: gateway, broker, timer"), ("skip", "Packet dropped / skipped"),
]
MERMAID_SHAPES = {
    "start": ('(["', '"])'), "end": ('(["', '"])'), "process": ('["', '"]'),
    "decision": ('{"', '"}'), "db": ('[("', '")]'), "queue": ('[/"', '"/]'),
    "alarm": ('["', '"]'), "ext": ('[["', '"]]'), "skip": ('["', '"]'),
}
MERMAID_CLASSES = {
    "decision": "fill:#fff2cc,stroke:#d6b656", "db": "fill:#d5e8d4,stroke:#82b366",
    "queue": "fill:#e1d5e7,stroke:#9673a6", "alarm": "fill:#f8cecc,stroke:#b85450",
    "ext": "fill:#ffffff,stroke:#666,stroke-dasharray:4", "skip": "fill:#eee,stroke:#999,color:#555",
    "process": "fill:#dae8fc,stroke:#6c8ebf",
}


def _x(col):
    return MARGIN_X + col * COL_W


def _y(row):
    return MARGIN_Y + row * ROW_H


def drawio(flow):
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    title = html.escape(f'{flow["number"]}. {flow["title"]}')
    cells.append(
        f'<mxCell id="title" value="{title}" style="text;html=1;fontSize=20;fontStyle=1;align=left;" '
        f'vertex="1" parent="1"><mxGeometry x="{MARGIN_X}" y="20" width="900" height="30" as="geometry"/></mxCell>'
    )
    summary = html.escape(flow["summary"])
    cells.append(
        f'<mxCell id="summary" value="{summary}" style="text;html=1;fontSize=12;align=left;whiteSpace=wrap;" '
        f'vertex="1" parent="1"><mxGeometry x="{MARGIN_X}" y="52" width="1100" height="40" as="geometry"/></mxCell>'
    )
    max_col = max_row = 0
    for node_id, (label, kind, col, row) in flow["nodes"].items():
        max_col, max_row = max(max_col, col), max(max_row, row)
        w = NODE_W + (30 if kind == "decision" else 0)
        h = NODE_H + (16 if kind == "decision" else 0)
        x = _x(col) + (NODE_W - w) / 2
        value = html.escape(label).replace("\n", "&lt;br&gt;")
        cells.append(
            f'<mxCell id="{node_id}" value="{value}" style="{STYLES[kind]}fontSize=11;" vertex="1" parent="1">'
            f'<mxGeometry x="{x:.0f}" y="{_y(row)}" width="{w}" height="{h}" as="geometry"/></mxCell>'
        )
    for index, edge in enumerate(flow["edges"]):
        src, dst, label = (edge + ("",))[:3]
        cells.append(
            f'<mxCell id="e{index}" value="{html.escape(label)}" '
            'style="edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;fontSize=10;labelBackgroundColor=#ffffff;" '
            f'edge="1" parent="1" source="{src}" target="{dst}"><mxGeometry relative="1" as="geometry"/></mxCell>'
        )
    # Files box (right) and legend (below the files box).
    files_x = _x(max_col + 1) + 20
    lines = "".join(
        f"<b>{html.escape(path)}</b><br>{html.escape(what)}<br><br>" for path, what in flow["files"]
    )
    files_h = 40 + 46 * len(flow["files"])
    cells.append(
        f'<mxCell id="files" value="{html.escape("<b>Files and functions</b><br><br>" + lines)}" '
        'style="rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;spacingLeft=8;spacingTop=6;'
        'fillColor=#fafafa;strokeColor=#bbbbbb;fontSize=10;" vertex="1" parent="1">'
        f'<mxGeometry x="{files_x}" y="{MARGIN_Y}" width="360" height="{files_h}" as="geometry"/></mxCell>'
    )
    legend_y = MARGIN_Y + files_h + 20
    for index, (kind, text) in enumerate(LEGEND):
        cells.append(
            f'<mxCell id="lg{index}" value="{html.escape(text)}" style="{STYLES[kind]}fontSize=9;" vertex="1" parent="1">'
            f'<mxGeometry x="{files_x + (index % 2) * 180}" y="{legend_y + (index // 2) * 40}" width="170" height="32" as="geometry"/></mxCell>'
        )
    width = files_x + 420
    height = max(_y(max_row) + 160, legend_y + 200)
    body = "".join(cells)
    return (
        '<mxfile host="generate.py"><diagram name="{}" id="{}">'
        '<mxGraphModel dx="1400" dy="900" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" '
        'arrows="1" fold="1" page="1" pageScale="1" pageWidth="{}" pageHeight="{}" math="0" shadow="0">'
        "<root>{}</root></mxGraphModel></diagram></mxfile>\n"
    ).format(html.escape(flow["title"]), flow["slug"], width, height, body)


def mermaid(flow):
    lines = ["flowchart TD"]
    for node_id, (label, kind, _, _) in flow["nodes"].items():
        left, right = MERMAID_SHAPES[kind]
        text = label.replace('"', "'").replace("\n", "<br/>")
        lines.append(f"    {node_id}{left}{text}{right}")
    for edge in flow["edges"]:
        src, dst, label = (edge + ("",))[:3]
        lines.append(f'    {src} -->|"{label}"| {dst}' if label else f"    {src} --> {dst}")
    for kind, style in MERMAID_CLASSES.items():
        members = [n for n, (_, k, _, _) in flow["nodes"].items() if k == kind]
        if members:
            lines.append(f"    classDef {kind} {style}")
            lines.append(f"    class {','.join(members)} {kind}")
    return "\n".join(lines)


def readme():
    out = [INTRO.strip(), "", "## Flows", ""]
    for flow in FLOWS:
        out.append(f'{flow["number"]}. [{flow["title"]}](#{flow["anchor"]})')
    out.append("")
    for flow in FLOWS:
        out += [
            f'## {flow["number"]}. {flow["title"]}',
            f'<a id="{flow["anchor"]}"></a>',
            "",
            flow["summary"],
            "",
            f'Diagram to open and edit in draw.io: [`drawio/{flow["slug"]}.drawio`](drawio/{flow["slug"]}.drawio)',
            "",
            "```mermaid",
            mermaid(flow),
            "```",
            "",
            flow["details"].strip(),
            "",
            "| File | Function / role |",
            "| --- | --- |",
        ]
        out += [f"| `{path}` | {what} |" for path, what in flow["files"]]
        out.append("")
    return "\n".join(out) + "\n"


def main():
    out_dir = HERE / "drawio"
    out_dir.mkdir(exist_ok=True)
    for flow in FLOWS:
        (out_dir / f'{flow["slug"]}.drawio').write_text(drawio(flow))
    (HERE / "README.md").write_text(readme())
    print(f"{len(FLOWS)} diagrams in {out_dir.relative_to(HERE.parent.parent)}/, README.md written")


if __name__ == "__main__":
    main()
