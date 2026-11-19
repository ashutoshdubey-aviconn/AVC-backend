"""Function-level merge check: which functions, classes, settings and API routes both sides changed.

    virtualwarehouse/bin/python scripts/merge/overlap_check.py --theirs DIR_OR_REF \
        [--base REF_OR_DIR ...] [--ours DIR] [--out CSV]

--theirs   the other code base: a folder (e.g. a copy of main's code or the colleague's checkout) or a git ref.
--base     what both sides started from; give every version the other side may be built on (git refs or
           folders). The first one is the legacy code. Default: origin/main and our branches / tags that main
           got files from (DEFAULT_BASES).
--ours     this branch (default: the current folder).

A git ref is extracted with `git archive` into .work/merge_trees/<ref>. Nothing is changed in the code.

Every function / method, every class's non-method body (model fields, Meta, serializer fields), every
module-level name (settings, urlpatterns, constants) and every URL route is compared by its *normalized*
source (ast.unparse: comments and formatting ignored) on the three sides:

    Same                     identical on both sides                      -> nothing to do
    Only ours changed        theirs = a base version, ours differs        -> keep ours
    Only theirs changed      ours = a base version, theirs differs        -> port their change into our file
    Both changed             neither side equals a base version           -> merge by hand (HIGH)
    Theirs only              exists only on their side, not in a base     -> port it (new on their side)
    Ours only                exists only on our side                      -> keep (new on our side)
    We replaced it           theirs = base, missing in ours               -> nothing (we moved / removed it)
    They removed it          in the legacy code and ours, not in theirs   -> check why
    Not on their side yet    from one of our branches, they have an older copy without it -> keep

A name is matched across files, so a view class that moved from wareApp/views.py to wareApp/views/site.py
is still compared with the same class on their side.
"""

import argparse
import ast
import csv
import hashlib
import pathlib
import re
import subprocess
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORK = ROOT / ".work" / "merge_trees"
# The legacy code first, then every branch / tag of ours that main's server got files from (checked 19 Nov:
# main's DG fuel and LoadData files equal these exactly).
DEFAULT_BASES = [
    "origin/main", "mains-migrated-with-zepto", "main-load-dg-fuel-repair-20261014", "origin/task_optimization",
    "origin/loaddatav1", "origin/fully_optimization", "origin/dg_fuel_v2", "origin/DgFuel", "origin/feature/celery",
    "origin/development", "mqtt-dgfuel-complete-v1", "DgFuel-v1.0",
]

# Live code only: migrations, tests and the many backup copies on the servers are left out.
SKIP_DIRS = {"migrations", "tests", "backups", "__pycache__", "venv", "virtualwarehouse", "node_modules", ".work",
             "static", "templates", "docs", "unit_tests", "logges"}
SKIP_FILE = re.compile(r"(bck|backup|_before_|\.save$|^\d|views\d|tasks\d|copy|_old\b|test_settings)", re.I)
CODE_DIRS = ("wareApp", "warehouse")

RISK = {
    "Both changed": "HIGH", "Theirs only": "HIGH", "Only theirs changed": "MEDIUM", "They removed it": "MEDIUM",
    "Different base versions": "MEDIUM", "Not on their side yet": "LOW", "Only ours changed": "LOW", "Ours only": "LOW", "We replaced it": "LOW",
    "Same": "-",
}
ACTION = {
    "Same": "Nothing to do.",
    "Only ours changed": "Keep ours (they did not change it).",
    "Only theirs changed": "Port their change into our version (file shown under 'Our file').",
    "Both changed": "Merge by hand: compare both versions with the base.",
    "Theirs only": "New on their side: port it into our code base.",
    "Ours only": "New on our side: keep.",
    "We replaced it": "Nothing: we moved / removed / replaced it and they did not change it.",
    "They removed it": "They deleted it: check whether our code still needs it.",
    "Not on their side yet": "Ours: they have an older copy of our work without it; keep.",
    "Different base versions": "Both sides are unchanged copies of different base versions: keep the newer (usually ours).",
}


def tree(spec):
    """A folder, or a git ref extracted into .work/merge_trees/<ref>."""
    p = pathlib.Path(spec)
    if p.is_dir():
        return p.resolve()
    dest = WORK / re.sub(r"[^A-Za-z0-9_.-]", "_", spec)
    if not dest.exists():
        dest.mkdir(parents=True)
        archive = subprocess.run(["git", "-C", str(ROOT), "archive", spec, *CODE_DIRS], capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(dest)], input=archive.stdout, check=True)
    return dest


def live_files(root):
    for d in CODE_DIRS:
        for f in sorted((root / d).rglob("*.py")):
            rel = f.relative_to(root)
            if SKIP_DIRS & set(rel.parts[:-1]) or SKIP_FILE.search(f.name):
                continue
            yield rel.as_posix(), f


def h(text):
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def items(root):
    """{key: [(file, line, hash, kind)]}; the last definition in a file wins, as in Python."""
    out = defaultdict(list)
    for rel, f in live_files(root):
        try:
            mod = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:
            print(f"skip {rel}: {exc}", file=sys.stderr)
            continue
        found = {}
        module = rel[:-3].replace("/", ".")

        def visit(body, prefix):
            for n in body:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found[("function", prefix + n.name)] = (n.lineno, h(ast.unparse(n)))
                elif isinstance(n, ast.ClassDef):
                    rest = [b for b in n.body if not isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))]
                    shell = ast.ClassDef(name=n.name, bases=n.bases, keywords=n.keywords,
                                         body=rest or [ast.Pass()], decorator_list=n.decorator_list)
                    found[("class body", prefix + n.name)] = (n.lineno, h(ast.unparse(shell)))
                    visit(n.body, prefix + n.name + ".")
                elif not prefix and isinstance(n, (ast.Assign, ast.AnnAssign)):
                    targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                    for t in targets:
                        if isinstance(t, ast.Name):
                            found[("setting", f"{module}:{t.id}")] = (n.lineno, h(ast.unparse(n)))

        visit(mod.body, "")
        for (kind, name), (line, digest) in found.items():
            out[(kind, name)].append((rel, line, digest))
        for route, view, line in routes(mod, rel):
            out[("url route", route)].append((rel, line, h(view)))
    return out


def routes(mod, rel):
    """(route, view expression, line) for every path()/re_path()/url() call in a urls.py."""
    if not rel.endswith("urls.py"):
        return []
    found = []
    for n in ast.walk(mod):
        if (isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) in ("path", "re_path", "url")
                and n.args and isinstance(n.args[0], ast.Constant) and len(n.args) > 1):
            view = ast.unparse(n.args[1]).replace("views.", "").replace(".as_view()", "")
            found.append((f"{n.args[0].value}", view, n.lineno))
    return found


def pick(entries, rel):
    """The entry in the same file if there is one, else all of them."""
    same = [e for e in entries if e[0] == rel]
    return same or entries


def compare(ours, theirs, bases):
    rows = []
    for key in sorted(set(ours) | set(theirs), key=lambda k: (k[0], k[1])):
        kind, name = key
        o, t = ours.get(key, []), theirs.get(key, [])
        base_hashes = {e[2] for b in bases for e in b.get(key, [])}
        if t and o:
            # compare each of their definitions with our matching one(s)
            for te in t:
                oe = pick(o, te[0])
                o_hashes = {e[2] for e in oe}
                if te[2] in o_hashes:
                    status = "Same"
                elif te[2] in base_hashes and not (o_hashes & base_hashes):
                    status = "Only ours changed"
                elif (o_hashes & base_hashes) and te[2] not in base_hashes:
                    status = "Only theirs changed"
                elif te[2] in base_hashes and (o_hashes & base_hashes):
                    status = "Different base versions"
                else:
                    status = "Both changed"
                rows.append(row(status, kind, name, [te], oe))
        elif t:
            status = "We replaced it" if all(e[2] in base_hashes for e in t) else "Theirs only"
            rows.append(row(status, kind, name, t, []))
        else:
            in_legacy = bool(bases[0].get(key))
            if base_hashes and all(e[2] in base_hashes for e in o):
                status = "They removed it" if in_legacy else "Not on their side yet"
            else:
                status = "Ours only"
            rows.append(row(status, kind, name, [], o))
    return rows


def row(status, kind, name, t, o):
    return {
        "Risk": RISK[status], "Status": status, "Kind": kind, "Name": name,
        "Their file": "; ".join(sorted({e[0] for e in t})), "Their line": t[0][1] if t else "",
        "Our file": "; ".join(sorted({e[0] for e in o})), "Our line": o[0][1] if o else "",
        "Action": ACTION[status],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--theirs", required=True)
    ap.add_argument("--base", action="append")
    ap.add_argument("--ours", default=str(ROOT))
    ap.add_argument("--out", default=str(ROOT / ".work" / "merge_overlap.csv"))
    ap.add_argument("--show-same", action="store_true", help="also write the 'Same' rows")
    args = ap.parse_args(argv)

    ours, theirs = items(tree(args.ours)), items(tree(args.theirs))
    bases = [items(tree(b)) for b in (args.base or DEFAULT_BASES)]
    rows = compare(ours, theirs, bases)
    counts = Counter((r["Risk"], r["Status"]) for r in rows)
    if not args.show_same:
        rows = [r for r in rows if r["Status"] != "Same"]
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "-": 3}
    rows.sort(key=lambda r: (order[r["Risk"]], r["Status"], r["Kind"], r["Name"]))
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["Risk"])
        w.writeheader()
        w.writerows(rows)
    for (risk, status), n in sorted(counts.items(), key=lambda x: (order[x[0][0]], x[0][1])):
        print(f"{risk:6} {status:24} {n:5}")
    print(f"written: {out}")


if __name__ == "__main__":
    main()
