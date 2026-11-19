"""API contract check: does the other code base answer every API the way our frontend expects?

    python3 scripts/merge/api_contract_check.py --ours DIR --theirs DIR [--frontend DIR] [--out CSV]

--ours      the code the frontend works with today (e.g. a copy of main's code)
--theirs    the code that would replace it (e.g. the colleague's checkout)
--frontend  the frontend source folder (default ~/Aviconncorp-new-migrated-frontend/src); marks the APIs it calls

Static only (ast, nothing is run). For every API view class that exists on both sides it records:
  - size of each side (lines of normalized source)
  - the request fields each side reads (request.data.get("x"), data["x"], request.GET.get("x"), ...)
  - the keys of the dict literals each side returns in Response(...) / JsonResponse(...)
  - whether their view only calls another view, or returns a fixed placeholder message
  - the route(s) of the view on our side, and whether the frontend calls them

Verdicts:
  Placeholder              returns a fixed message, no data / file
  Calls X instead          only passes the request to another view X (check X)
  Same response keys       same keys returned
  Same keys plus extras    every key of ours is still returned, plus new ones
  Response keys differ     some keys we return are missing on their side -> the frontend breaks
  No literal keys          both build the response another way (serializer / list): check by hand
"Contract differs" = placeholder, or response keys differ, or the request fields differ.
A static check can be wrong where a response is built in a helper: treat it as a list to test, not as proof.
"""

import argparse
import ast
import csv
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
REQUEST_OBJS = ("data", "request.data", "request.GET", "request.query_params", "request.POST", "params", "payload")
PLACEHOLDER = re.compile(r"Response\(\s*\{\s*['\"](message|msg|status)['\"]\s*:\s*['\"][^'\"]*"
                         r"(ready|placeholder|demo|todo|not implemented)", re.I)


def view_files(root):
    files = [root / "wareApp" / "views.py", root / "wareApp" / "recovery" / "views.py"]
    files += sorted((root / "wareApp" / "views").glob("*.py"))
    return [f for f in files if f.exists()]


def classes(root):
    out = {}
    for f in view_files(root):
        for n in ast.parse(f.read_text(errors="replace")).body:
            if isinstance(n, ast.ClassDef):
                out[n.name] = (n, f.relative_to(root).as_posix())
    return out


def response_keys(cls):
    keys = set()
    for n in ast.walk(cls):
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") in ("Response", "JsonResponse"):
            for arg in n.args[:1]:
                for d in ast.walk(arg):
                    if isinstance(d, ast.Dict):
                        keys |= {k.value for k in d.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return keys


def request_fields(cls):
    keys = set()
    for n in ast.walk(cls):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("get", "getlist") and n.args
                and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)
                and ast.unparse(n.func.value) in REQUEST_OBJS):
            keys.add(n.args[0].value)
        if (isinstance(n, ast.Subscript) and ast.unparse(n.value) in REQUEST_OBJS and isinstance(n.slice, ast.Constant)
                and isinstance(n.slice.value, str)):
            keys.add(n.slice.value)
    return keys


def delegates_to(cls):
    """Name of the view this class only passes the request to, or ''."""
    for n in ast.walk(cls):
        if (isinstance(n, ast.Return) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
                and isinstance(n.value.func.value, ast.Call)):
            return ast.unparse(n.value.func.value.func)
    if cls.bases and not any(isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)) for b in cls.body):
        base = ast.unparse(cls.bases[0])
        if base not in ("APIView", "GenericAPIView", "View"):
            return base
    return ""


def routes(root):
    """{view class: [route, ...]} from every urls.py."""
    out = {}
    for f in list((root / "wareApp").rglob("urls.py")) + [root / "warehouse" / "urls.py"]:
        if not f.exists() or re.search(r"backup|bck", str(f), re.I):
            continue
        try:
            mod = ast.parse(f.read_text(errors="replace"))
        except SyntaxError:
            continue
        for n in ast.walk(mod):
            if (isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) in ("path", "re_path", "url")
                    and n.args and isinstance(n.args[0], ast.Constant) and len(n.args) > 1):
                view = ast.unparse(n.args[1]).replace(".as_view()", "").split(".")[-1]
                out.setdefault(view, []).append(n.args[0].value)
    return out


def frontend_text(folder):
    if not folder.is_dir():
        return ""
    return "\n".join(p.read_text(errors="ignore") for p in folder.rglob("*")
                     if p.suffix in (".js", ".jsx", ".ts", ".tsx") and "node_modules" not in p.parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ours", required=True)
    ap.add_argument("--theirs", required=True)
    ap.add_argument("--frontend", default=str(pathlib.Path.home() / "Aviconncorp-new-migrated-frontend" / "src"))
    ap.add_argument("--out", default=str(ROOT / ".work" / "api_contract.csv"))
    args = ap.parse_args(argv)
    ours_root, theirs_root = pathlib.Path(args.ours), pathlib.Path(args.theirs)
    ours, theirs = classes(ours_root), classes(theirs_root)
    our_routes, their_routes = routes(ours_root), routes(theirs_root)
    their_paths = {r for rs in their_routes.values() for r in rs}
    fe = frontend_text(pathlib.Path(args.frontend))

    def called(route):
        stem = route.split("<")[0].strip("/")
        return bool(fe) and bool(stem) and stem in fe

    rows = []
    for name in sorted(set(ours) | set(theirs)):
        o, t = ours.get(name), theirs.get(name)
        rs = our_routes.get(name) or their_routes.get(name) or []
        row = {"View": name, "Route": "; ".join(rs), "Frontend calls it": "yes" if any(called(r) for r in rs) else "",
               "Our file": o[1] if o else "", "Their file": t[1] if t else ""}
        if o and t:
            o_src, t_src = ast.unparse(o[0]), ast.unparse(t[0])
            o_keys, t_keys = response_keys(o[0]), response_keys(t[0])
            o_req, t_req = request_fields(o[0]), request_fields(t[0])
            target = delegates_to(t[0])
            if o_src == t_src:
                verdict = "Same code"
            elif PLACEHOLDER.search(t_src):
                verdict = "Placeholder"
            elif target:
                verdict = f"Calls {target} instead"
            elif not o_keys and not t_keys:
                verdict = "No literal keys"
            elif o_keys == t_keys:
                verdict = "Same response keys"
            elif not o_keys - t_keys:
                verdict = "Same keys plus extras"
            else:
                verdict = "Response keys differ"
            req_differs = o_req != t_req and not verdict.startswith(("Calls", "Same code"))
            differs = verdict in ("Placeholder", "Response keys differ") or req_differs
            row.update({
                "Verdict": verdict, "Contract differs": "yes" if differs else "",
                "Our lines": o_src.count("\n") + 1, "Their lines": t_src.count("\n") + 1,
                "Response keys only ours": ", ".join(sorted(o_keys - t_keys)),
                "Response keys only theirs": ", ".join(sorted(t_keys - o_keys)),
                "Request fields only ours": ", ".join(sorted(o_req - t_req)),
                "Request fields only theirs": ", ".join(sorted(t_req - o_req)),
            })
        else:
            missing_route = o and rs and not (set(rs) & their_paths)
            row.update({"Verdict": "Only ours" if o else "Only theirs",
                        "Contract differs": "yes" if missing_route and row["Frontend calls it"] else "",
                        "Our lines": ast.unparse(o[0]).count("\n") + 1 if o else "",
                        "Their lines": ast.unparse(t[0]).count("\n") + 1 if t else ""})
        rows.append(row)

    cols = ["View", "Route", "Frontend calls it", "Verdict", "Contract differs", "Our lines", "Their lines",
            "Response keys only ours", "Response keys only theirs", "Request fields only ours", "Request fields only theirs",
            "Our file", "Their file"]
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, restval="")
        w.writeheader()
        w.writerows(rows)
    both = [r for r in rows if r["Verdict"] not in ("Only ours", "Only theirs")]
    used = [r for r in both if r["Frontend calls it"]]
    print(f"views on both sides {len(both)}; contract differs {sum(bool(r['Contract differs']) for r in both)}")
    print(f"called by the frontend {len(used)}; of those contract differs {sum(bool(r['Contract differs']) for r in used)}")
    print(f"only ours {sum(r['Verdict'] == 'Only ours' for r in rows)}, only theirs {sum(r['Verdict'] == 'Only theirs' for r in rows)}")
    print(f"written: {out}")


if __name__ == "__main__":
    main()
