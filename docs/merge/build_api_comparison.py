"""Build API_COMPARISON_COLLEAGUE_VS_OURS.xlsx: every API route, his vs ours, and what each does.

Static (ast); nothing is run. "What it does" is generated from each view's code: HTTP methods,
login rule, models it reads and writes, request fields, response keys, placeholder / forwarding,
plus the first line of its docstring when it has one. Decisions come from
views_merge_decisions_20261121.csv (21 Nov views merge).

"Main vs his" sheets: does his code have every API the main server has? Main is read from a
read-only snapshot of its urls.py, views.py, recovery/ and models.py in .work/main_snapshot_20261125
(copied over ssh with cat/tar; nothing on main changed). Main's default permission is
[AllowAny, IsAuthenticated]; DRF needs all of them, so "default" on main means login required.

    virtualwarehouse/bin/python docs/merge/build_api_comparison.py
"""

import ast
import csv
import pathlib
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "merge"))
import api_contract_check as acc  # noqa: E402

THEIRS = ROOT / ".work" / "colleague_repo"
FRONTEND = pathlib.Path.home() / "Aviconncorp-new-migrated-frontend" / "src"
DECISIONS = pathlib.Path(__file__).with_name("views_merge_decisions_20261121.csv")
OUT = pathlib.Path(__file__).with_name("API_COMPARISON_COLLEAGUE_VS_OURS.xlsx")
MAIN = ROOT / ".work" / "main_snapshot_20261125"
MAIN_DATE = "25 Nov 2026"

FONT = "Arial"
HEAD_FILL = PatternFill("solid", fgColor="14213D")
FILL = {
    "Only his": PatternFill("solid", fgColor="FFE6D3"),
    "Only ours": PatternFill("solid", fgColor="DDEBD8"),
    "Differs": PatternFill("solid", fgColor="FFF4C2"),
    "Missing in his": PatternFill("solid", fgColor="F8D3D3"),
    "Frontend would fail": PatternFill("solid", fgColor="F8D3D3"),
    "Login rule changed": PatternFill("solid", fgColor="FFF4C2"),
    "Same": PatternFill("solid", fgColor="DDEBD8"),
}
THIN = Side(style="thin", color="C8CCD2")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
HTTP = ("get", "post", "put", "patch", "delete")
WRITE_CALLS = {"create", "bulk_create", "get_or_create", "update_or_create", "update", "delete", "bulk_update"}


# ------------------------------------------------------------------ routes

def url_routes(root):
    """[(route, view name, viewset actions)] from wareApp/urls.py and wareApp/recovery/urls.py."""
    out = []
    for f, prefix in ((root / "wareApp" / "urls.py", ""), (root / "wareApp" / "recovery" / "urls.py", "v1/recovery/")):
        if not f.exists():
            continue
        for n in ast.walk(ast.parse(f.read_text(errors="replace"))):
            if (isinstance(n, ast.Call) and getattr(n.func, "id", "") in ("path", "re_path") and len(n.args) > 1
                    and isinstance(n.args[0], ast.Constant)):
                target = n.args[1]
                if isinstance(target, ast.Call) and getattr(target.func, "id", "") == "include":
                    continue
                actions = ""
                if isinstance(target, ast.Call) and isinstance(target.func, ast.Attribute) and target.func.attr == "as_view":
                    if target.args and isinstance(target.args[0], ast.Dict):
                        actions = ", ".join(f"{ast.literal_eval(k).upper()}={ast.literal_eval(v)}"
                                            for k, v in zip(target.args[0].keys, target.args[0].values))
                    name = ast.unparse(target.func.value).split(".")[-1]
                else:
                    name = ast.unparse(target).split(".")[-1]
                out.append((prefix + n.args[0].value, name, actions))
    return out


# ------------------------------------------------------------------ describing a view

def methods(cls):
    return [f.name.upper() for f in cls.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name in HTTP]


def class_attr(cls, name):
    for s in cls.body:
        if isinstance(s, ast.Assign) and any(getattr(t, "id", "") == name for t in s.targets):
            return ast.unparse(s.value)
    return ""


def login_rule(cls):
    perm = class_attr(cls, "permission_classes")
    if not perm:
        rule = "Login required (default)"
    elif "AllowAny" in perm:
        rule = "Open: no login (AllowAny)"
    elif perm in ("[]", "()"):
        rule = "Open: no permission check ([])"
    elif "IsAuthenticated" in perm:
        rule = "Login required"
    else:
        rule = perm
    src = ast.unparse(cls)
    if "UserType" in src and ("PermissionDenied" in src or "!= 1" in src or "== 1" in src):
        rule += "; checks user type"
    throttle = class_attr(cls, "throttle_classes")
    if throttle == "[]":
        rule += "; no rate limit"
    elif throttle:
        rule += f"; rate limit {throttle}"
    return rule


def models_used(cls, known):
    reads, writes = set(), set()
    for n in ast.walk(cls):
        if isinstance(n, ast.Attribute) and n.attr == "objects" and isinstance(n.value, ast.Name) and n.value.id in known:
            reads.add(n.value.id)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            chain = ast.unparse(n.func)
            if n.func.attr in WRITE_CALLS:
                for m in known:
                    if chain.startswith(m + ".objects"):
                        writes.add(m)
            if n.func.attr == "save" and isinstance(n.func.value, ast.Name):
                writes.add(f"({n.func.value.id}).save")
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in known:
            writes.add(n.func.id)  # Model(...) then save()
    return sorted(reads), sorted(w for w in writes if not w.startswith("("))


def docline(cls):
    doc = ast.get_docstring(cls) or ""
    for f in cls.body:
        if not doc and isinstance(f, ast.FunctionDef) and f.name in HTTP:
            doc = ast.get_docstring(f) or ""
    para = doc.strip().split("\n\n")[0]
    text = " ".join(line.strip() for line in para.splitlines())
    return text if len(text) <= 260 else text[:257].rsplit(" ", 1)[0] + "..."


def describe(cls, known):
    if cls is None:
        return {}
    src = ast.unparse(cls)
    reads, writes = models_used(cls, known)
    req = sorted(acc.request_fields(cls))
    resp = sorted(acc.response_keys(cls))
    fwd = acc.delegates_to(cls)
    if acc.PLACEHOLDER.search(src):
        summary = "PLACEHOLDER: returns a fixed message, no data or file."
    elif fwd and not reads:
        summary = f"Forwards the request to {fwd}."
    else:
        parts = []
        if "openpyxl" in src or "xlsxwriter" in src or "HttpResponse(" in src and "attachment" in src:
            parts.append("Builds an Excel / file download")
        if writes:
            parts.append("Saves to " + ", ".join(writes))
        if reads:
            parts.append("Reads " + ", ".join(r for r in reads if r not in writes) if set(reads) - set(writes) else "")
        if req:
            parts.append("Takes " + ", ".join(req))
        if resp:
            parts.append("Returns " + ", ".join(resp[:12]) + (" ..." if len(resp) > 12 else ""))
        elif "serializer" in src.lower():
            parts.append("Returns serializer data")
        summary = ". ".join(p for p in parts if p) + "." if parts else "(no data access found)"
    doc = docline(cls)
    if doc:
        summary = f"{doc} | {summary}"
    return {
        "methods": ", ".join(methods(cls)) or "(viewset / function)",
        "login": login_rule(cls),
        "reads": ", ".join(reads),
        "writes": ", ".join(writes),
        "request": ", ".join(req),
        "response": ", ".join(resp),
        "summary": summary,
        "lines": len(src.splitlines()),
    }


def known_models(root):
    names = set()
    paths = [root / "wareApp" / "models.py"] + sorted((root / "wareApp" / "models").glob("*.py"))
    for p in paths:
        if p.exists():
            for n in ast.parse(p.read_text(errors="replace")).body:
                if isinstance(n, ast.ClassDef):
                    names.add(n.name)
    names |= {"User", "Token", "Group"}
    return names


# ------------------------------------------------------------------ workbook helpers

def header(ws, row, cols):
    for i, h in enumerate(cols, 1):
        c = ws.cell(row=row, column=i, value=h)
        c.font = Font(name=FONT, bold=True, color="FFFFFF")
        c.fill = HEAD_FILL
        c.alignment = Alignment(wrap_text=True, vertical="center")
        c.border = BORDER


def table(ws, start, cols, rows, widths, fill_col=None):
    header(ws, start, cols)
    for r, data in enumerate(rows, start + 1):
        for c, v in enumerate(data, 1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.font = Font(name=FONT, size=10)
            cell.alignment = WRAP
            cell.border = BORDER
        if fill_col is not None:
            f = FILL.get(data[fill_col])
            if f:
                ws.cell(row=r, column=1).fill = f
                ws.cell(row=r, column=fill_col + 1).fill = f
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row=start + 1, column=2)
    end = start + len(rows)
    ws.auto_filter.ref = f"A{start}:{get_column_letter(len(cols))}{max(end, start)}"
    return end


def title(ws, text, sub=""):
    ws["A1"] = text
    ws["A1"].font = Font(name=FONT, bold=True, size=14, color="14213D")
    if sub:
        ws["A2"] = sub
        ws["A2"].font = Font(name=FONT, italic=True, size=10, color="4E5A6B")


# ------------------------------------------------------------------ main server vs his

def open_or_login(rule):
    return "open" if (rule or "").startswith("Open") else ("login" if rule else "")


def frontend_methods(fe, route):
    """HTTP methods the frontend uses for a route: http.get(... 'route' ...) / http.post(...)."""
    import re
    stem = route.split("<")[0]
    if not fe or not stem.strip("/"):
        return ""
    pat = re.compile(r"http\.(get|post|put|patch|delete)\s*(?:<[^(]*?>)?\s*\((?:(?!http\.)[^;])*?['\"`]" + re.escape(stem) + r"['\"`]", re.S)
    return ", ".join(sorted({m.upper() for m in pat.findall(fe)}))


def main_vs_his_rows(fe, called):
    main_cls, his_cls, ours_cls = acc.classes(MAIN), acc.classes(THEIRS), acc.classes(ROOT)
    main_models, his_models = known_models(MAIN), known_models(THEIRS)
    main_r = {r: (v, a) for r, v, a in url_routes(MAIN)}
    his_r = {r: (v, a) for r, v, a in url_routes(THEIRS)}
    ours_r = {r for r, _, _ in url_routes(ROOT)}
    rows = []
    for route in sorted(set(main_r) | set(his_r), key=str.lower):
        mv, ma = main_r.get(route, ("", ""))
        hv, ha = his_r.get(route, ("", ""))
        m = describe(main_cls[mv][0], main_models) if mv in main_cls else {}
        h = describe(his_cls[hv][0], his_models) if hv in his_cls else {}
        fem = frontend_methods(fe, route)
        problems, effect = [], []
        if mv and not hv:
            status = "Missing in his"
            effect.append("Frontend calls it: that screen would break" if called(route) else "Frontend does not call it")
        elif hv and not mv:
            status = "Only his"
        else:
            status = "Same"
            hm = set((h.get("methods") or "").replace(" ", "").split(",")) - {""}
            if "ViewSet" not in hv and fem and hm and not set(fem.replace(" ", "").split(",")) <= hm:
                status = "Frontend would fail"
                problems.append(f"frontend sends {fem}; his accepts {', '.join(sorted(hm))}")
                effect.append("405 Method Not Allowed")
            if m.get("methods") != h.get("methods") and "ViewSet" not in hv:
                problems.append(f"methods {m.get('methods') or '-'} -> {h.get('methods') or '-'}")
            ml, hl = open_or_login(m.get("login")), open_or_login(h.get("login"))
            if ml and hl and ml != hl:
                problems.append(f"login: {ml} on main -> {hl} in his")
                if hl == "open":
                    effect.append("anyone can call it without login")
                elif called(route) and fem:
                    effect.append("needs a token now: check the frontend sends one")
                if status == "Same":
                    status = "Login rule changed"
            if mv != hv:
                problems.append(f"view {mv} -> {hv}")
        rows.append([route, status, called(route), fem,
                     mv + (f" ({ma})" if ma else ""), m.get("methods", ""), m.get("login", ""),
                     hv + (f" ({ha})" if ha else ""), his_cls[hv][1] if hv in his_cls else "", h.get("methods", ""), h.get("login", ""),
                     "yes" if route in ours_r else "", "; ".join(problems), "; ".join(effect)])
    return rows


def add_main_vs_his(wb, fe, called):
    rows = main_vs_his_rows(fe, called)
    cols = ["Route", "Status", "Frontend calls it", "Frontend method",
            "Main view", "Main methods", "Main login rule",
            "His view", "His file", "His methods", "His login rule",
            "In our code", "Difference", "Effect"]
    widths = [34, 18, 9, 10, 32, 10, 24, 32, 26, 10, 24, 8, 50, 40]
    sub = (f"Main server snapshot {MAIN_DATE} (read only) vs Daksh's code @ 54313d5. "
           "Main default permission = login required.")
    for name, keep in (("Main vs his", lambda r: True),
                       ("Main vs his - problems", lambda r: r[1] != "Same")):
        sel = [r for r in rows if keep(r)]
        sh = wb.create_sheet(name)
        title(sh, f"{name}: {len(sel)} routes", sub)
        table(sh, 3, cols, sel, widths, fill_col=1)
    return rows


# ------------------------------------------------------------------ build

def build():
    ours_cls, his_cls = acc.classes(ROOT), acc.classes(THEIRS)
    ours_models, his_models = known_models(ROOT), known_models(THEIRS)
    our_routes, his_routes = url_routes(ROOT), url_routes(THEIRS)
    fe = acc.frontend_text(FRONTEND)
    decisions = {}
    if DECISIONS.exists():
        with DECISIONS.open() as fh:
            decisions = {r["View"]: r for r in csv.DictReader(fh)}

    def called(route):
        stem = route.split("<")[0].strip("/")
        return "yes" if fe and stem and stem in fe else ""

    by_route = {}
    for route, view, actions in our_routes:
        by_route.setdefault(route, {})["ours"] = (view, actions)
    for route, view, actions in his_routes:
        by_route.setdefault(route, {})["his"] = (view, actions)

    rows = []
    for route in sorted(by_route, key=lambda r: r.lower()):
        sides = by_route[route]
        ov, oa = sides.get("ours", ("", ""))
        hv, ha = sides.get("his", ("", ""))
        o = describe(ours_cls[ov][0], ours_models) if ov in ours_cls else {}
        h = describe(his_cls[hv][0], his_models) if hv in his_cls else {}
        if ov and not hv:
            status = "Only ours"
        elif hv and not ov:
            status = "Only his"
        else:
            same_req = o.get("request") == h.get("request")
            same_resp = o.get("response") == h.get("response")
            same_m = o.get("methods") == h.get("methods")
            placeholder = h.get("summary", "").startswith("PLACEHOLDER")
            status = "Same API" if same_req and same_resp and same_m and not placeholder else "Differs"
        notes = []
        if status == "Differs":
            if o.get("methods") != h.get("methods"):
                notes.append(f"method {o.get('methods')} -> {h.get('methods')}")
            if (o.get("login") or "").replace(" (default)", "") != (h.get("login") or "").replace(" (default)", ""):
                notes.append(f"login: {o.get('login')} -> {h.get('login')}")
            if o.get("request") != h.get("request"):
                notes.append("request fields differ")
            if o.get("response") != h.get("response"):
                notes.append("response keys differ")
            if h.get("summary", "").startswith("PLACEHOLDER"):
                notes.append("his is a placeholder")
            if o.get("reads") != h.get("reads"):
                notes.append(f"data: {o.get('reads') or '-'} -> {h.get('reads') or '-'}")
        dec = decisions.get(ov or hv, {})
        rows.append([
            route, status, called(route),
            hv + (f" ({ha})" if ha else ""), h.get("methods", ""), h.get("login", ""), h.get("summary", ""),
            h.get("request", ""), h.get("response", ""), h.get("lines", ""),
            ov + (f" ({oa})" if oa else ""), o.get("methods", ""), o.get("login", ""), o.get("summary", ""),
            o.get("request", ""), o.get("response", ""), o.get("lines", ""),
            "; ".join(notes), dec.get("Decision", ""), dec.get("Why", ""),
        ])

    wb = Workbook()
    ws = wb.active
    ws.title = "Start here"
    title(ws, "APIs: Daksh's code vs ours, and what each does",
          "Static review, 21 Nov 2026. His repo 54313d5 (read only, nothing uploaded). Ours: full-optimization-v2 (local).")
    info = [
        ("All APIs", "One row per route (URL under /api/). His view and ours side by side: methods, login rule, what it does, request fields, response keys, size."),
        ("Only his", "Routes that exist only in his code."),
        ("Only ours", "Routes that exist only in our code."),
        ("Differs", "Routes on both sides that answer differently."),
        ("Status", "Same API = same methods, request fields and response keys. Differs = something the frontend sees changes. Only his / Only ours = route on one side."),
        ("What it does", "Generated from the code (models read / saved, fields, keys, placeholder, forwarding) plus the view's docstring. A response built in a helper or serializer shows no keys: check by hand."),
        ("Frontend", "yes = the route text appears in ~/Aviconncorp-new-migrated-frontend/src."),
        ("Decision", "From the 21 Nov views merge (views_merge_decisions_20261121.csv)."),
        ("Main vs his", f"Every route on the main server ({MAIN_DATE}, read-only snapshot) next to his code: missing routes, methods the frontend sends that his view does not accept, and login rule changes."),
        ("Main vs his - problems", "Only the rows of Main vs his that are not the same."),
        ("Rebuild", "virtualwarehouse/bin/python docs/merge/build_api_comparison.py"),
    ]
    for i, (k, v) in enumerate(info, 4):
        ws.cell(row=i, column=1, value=k).font = Font(name=FONT, bold=True)
        c = ws.cell(row=i, column=2, value=v)
        c.font = Font(name=FONT)
        c.alignment = WRAP
    n = len(rows)
    rng = f"'All APIs'!$B$4:$B${3 + n}"
    fe_rng = f"'All APIs'!$C$4:$C${3 + n}"
    r0 = 4 + len(info) + 1
    ws.cell(row=r0, column=1, value="Counts (formulas)").font = Font(name=FONT, bold=True, size=12)
    counts = [
        ("Routes in total", f"=COUNTA({rng})"),
        ("Same API on both sides", f'=COUNTIF({rng},"Same API")'),
        ("On both sides but different", f'=COUNTIF({rng},"Differs")'),
        ("Only his", f'=COUNTIF({rng},"Only his")'),
        ("Only ours", f'=COUNTIF({rng},"Only ours")'),
        ("Called by the frontend", f'=COUNTIF({fe_rng},"yes")'),
        ("Called by the frontend and different", f'=COUNTIFS({rng},"Differs",{fe_rng},"yes")'),
        ("Called by the frontend and missing in his", f'=COUNTIFS({rng},"Only ours",{fe_rng},"yes")'),
    ]
    for i, (k, f) in enumerate(counts, r0 + 1):
        ws.cell(row=i, column=1, value=k).font = Font(name=FONT)
        c = ws.cell(row=i, column=2, value=f)
        c.font = Font(name=FONT, bold=True)
        c.alignment = Alignment(horizontal="left")
    r1 = r0 + len(counts) + 2
    ws.cell(row=r1, column=1, value="Colours").font = Font(name=FONT, bold=True)
    for i, k in enumerate(("Only his", "Only ours", "Differs"), r1 + 1):
        c = ws.cell(row=i, column=1, value=k)
        c.font = Font(name=FONT)
        c.fill = FILL[k]
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 120

    cols = ["Route", "Status", "Frontend calls it",
            "His view", "His methods", "His login rule", "His: what it does", "His request fields", "His response keys", "His lines",
            "Our view", "Our methods", "Our login rule", "Ours: what it does", "Our request fields", "Our response keys", "Our lines",
            "Differences", "Merge decision (21 Nov)", "Why"]
    widths = [34, 11, 9, 30, 10, 22, 60, 24, 30, 7, 30, 10, 22, 60, 24, 30, 7, 40, 18, 50]
    for name, flt in (("All APIs", None), ("Only his", "Only his"), ("Only ours", "Only ours"), ("Differs", "Differs")):
        sheet = ws if False else wb.create_sheet(name)
        sel = [r for r in rows if flt is None or r[1] == flt]
        title(sheet, f"{name}: {len(sel)} routes", "His = Daksh's code @ 54313d5; ours = full-optimization-v2.")
        table(sheet, 3, cols, sel, widths, fill_col=1)

    mrows = add_main_vs_his(wb, fe, called)
    mrng = f"'Main vs his'!$B$4:$B${3 + len(mrows)}"
    r2 = r1 + 5
    ws.cell(row=r2, column=1, value="Main server vs his (formulas)").font = Font(name=FONT, bold=True, size=12)
    for i, (k, f) in enumerate((
            ("Routes on main", f'=COUNTA({mrng})-COUNTIF({mrng},"Only his")'),
            ("Same on main and his", f'=COUNTIF({mrng},"Same")'),
            ("Missing in his", f'=COUNTIF({mrng},"Missing in his")'),
            ("Frontend would fail (wrong method)", f'=COUNTIF({mrng},"Frontend would fail")'),
            ("Login rule changed", f'=COUNTIF({mrng},"Login rule changed")'),
            ("Only his (not on main)", f'=COUNTIF({mrng},"Only his")')), r2 + 1):
        ws.cell(row=i, column=1, value=k).font = Font(name=FONT)
        c = ws.cell(row=i, column=2, value=f)
        c.font = Font(name=FONT, bold=True)
        c.alignment = Alignment(horizontal="left")

    wb.save(OUT)
    from collections import Counter
    print(f"Wrote {OUT}: {n} routes", dict(Counter(r[1] for r in rows)))
    print("Main vs his:", dict(Counter(r[1] for r in mrows)))


if __name__ == "__main__":
    build()
