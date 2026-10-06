#!/usr/bin/env python3
"""Runs every test case through the app and through the independent Python reference, and compares them.

    python3 tests/run_tests.py                 # all cases in tests/cases
    python3 tests/run_tests.py 03 07           # cases whose file name starts with 03 or 07
    python3 tests/run_tests.py --app-json f    # reuse app results saved by an earlier run (no browser)

Writes tests/output/report.md (plus the raw results as JSON) and exits with 1 if any check fails.

Check levels
  FAIL  the app disagrees with the reference or with a hand-derived number beyond the tolerance set below
  WARN  a known limit of the method the app uses, not a bug: its regression EVPPI is off the near-exact value
  INFO  printed for context only: the article's own published figures, which use other inputs
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reference  # noqa: E402

# ----------------------------------------------------------------------------------------------------------------
# Tolerances, set before looking at results. "scale" is the widest middle-95% spread of any option in the case
# (at least 1), so tolerances on money follow the size of the decision.
# ----------------------------------------------------------------------------------------------------------------
TOL = {
    "point_rel": 1e-6,          # values at the likely values (the app's normal-curve functions are approximations)
    "switch_rel": 1e-6,         # switch points, relative to the width of the sweep
    "draw_rel": 1e-3,           # first draws of each range, relative to its width (the app inverts on a grid)
    "mean_scale": 2e-4,         # averages over the same worlds
    "quantile_scale": 1e-3,     # 2.5% / 97.5% points over the same worlds
    "share": 0.002,             # shares of worlds (best in, beats): 20 worlds in 10,000 may sit on a tie
    "bad_worlds": 0.001,        # share of worlds whose chances do not fit
    "evppi_rel": 0.01,          # app EVPPI vs the same regression estimator
    "evppi_exact_rel": 0.10,    # WARN: app EVPPI vs near-exact, ... or 2% of EVPI, whichever is larger
    "evppi_exact_evpi": 0.02,
    "independent_se": 4.0,      # independent stream: within 4 standard errors
    "post": 1e-9,               # posteriors after the diagnostic month
    "pk_grid": 1 / 201,         # the app reads the diagnostic band on a 1/201 grid
}


class Report:
    def __init__(self):
        self.rows = []

    def add(self, case, section, what, ok, app=None, ref=None, expected=None, level="FAIL", note=""):
        status = "PASS" if ok else level
        self.rows.append(dict(case=case, section=section, what=what, status=status, app=app, ref=ref, expected=expected, note=note))
        return ok

    def count(self, case=None):
        out = {"PASS": 0, "FAIL": 0, "WARN": 0, "INFO": 0}
        for r in self.rows:
            if case is None or r["case"] == case:
                out[r["status"]] += 1
        return out


def close(a, b, tol):
    return a is not None and b is not None and math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tol


def fmt(x):
    if x is None:
        return "—"
    if isinstance(x, bool) or isinstance(x, str):
        return str(x)
    if isinstance(x, (list, tuple)):
        return "[" + ", ".join(fmt(v) for v in x) + "]"
    if isinstance(x, dict):
        return "{" + ", ".join(f"{k}: {fmt(v)}" for k, v in x.items()) + "}"
    if x == 0:
        return "0"
    a = abs(x)
    if a >= 1000:
        return f"{x:,.2f}"
    if a >= 1:
        return f"{x:.4f}".rstrip("0").rstrip(".")
    return f"{x:.6g}"


# ----------------------------------------------------------------------------------------------------------------
# Results from the app, put into the same shape as the reference's
# ----------------------------------------------------------------------------------------------------------------
def run_app(case_files, node_path=None):
    env = dict(os.environ)
    if not env.get("NODE_PATH"):
        env["NODE_PATH"] = node_path or subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    p = subprocess.run(["node", str(HERE / "app_runner.js"), *map(str, case_files)], capture_output=True, text=True, env=env)
    if p.returncode != 0:
        sys.exit(f"The app runner failed:\n{p.stderr}")
    return json.loads(p.stdout)


def normalize_app(r):
    out = dict(r)
    out["breakevens"] = {b["name"]: b for b in r.get("breakevens", [])}
    out["evppi"] = {x["name"]: x["v"] for x in r.get("evppi", []) if x["name"]}
    return out


# ----------------------------------------------------------------------------------------------------------------
# Named results, used by the hand-derived checks in the case files
# ----------------------------------------------------------------------------------------------------------------
def metric(res, key):
    kind, _, arg = key.partition(":")
    opts = res["options"]
    sim = res.get("sim") or {}
    if kind == "point":
        return res["point"][opts.index(arg)]
    if kind == "leader":
        return opts[res["pointLeader"]]
    if kind == "mean_leader":
        return opts[sim["meanLeader"]]
    if kind == "scope":
        return res["scope"].get(arg)
    if kind == "switches":
        be = res["breakevens"].get(arg)
        return None if be is None else [{"at": c["at"], "from": opts[c["from"]], "to": opts[c["to"]], "inRange": c["inRange"]} for c in be["crossings"]]
    if kind == "pbest":
        return sim["opts"][opts.index(arg)]["pBest"]
    if kind == "mean":
        return sim["opts"][opts.index(arg)]["mean"]
    if kind == "evpi":
        return sim["evpi"]
    if kind == "bad_share":
        return sim["badWorlds"] / sim["N"]
    if kind == "pair":
        return opts[res["pair"]["b"]] if arg == "challenger" else res["pair"][arg]
    if kind == "evppi":
        return res["evppi"].get(arg)
    if kind == "evppi_equals_evpi":
        return (res["evppi"][arg] - sim["evpi"]) / max(sim["evpi"], 1.0)
    if kind == "diag":
        d = res.get("diag") or {}
        if arg in ("pos_best", "neg_best"):
            return opts[d[arg[:3]]["bestIdx"]]
        return d.get(arg)
    if kind == "pk_window":
        return (res.get("diag") or {}).get("pkWindows")
    raise KeyError(key)


def matches(key, got, expected, tol, grid=False):
    """Compares one named result with its expected value. Returns (ok, note)."""
    if got is None:
        return False, "missing"
    if isinstance(expected, str) or isinstance(expected, bool):
        return got == expected, ""
    if key.startswith("switches:"):
        if len(got) != len(expected):
            return False, f"{len(got)} switch points, expected {len(expected)}"
        for g, e in zip(got, expected):
            if not close(g["at"], e["at"], tol):
                return False, f"at {fmt(g['at'])}, expected {fmt(e['at'])}"
            for k in ("from", "to", "inRange"):
                if k in e and g[k] != e[k]:
                    return False, f"{k} = {g[k]}, expected {e[k]}"
        return True, ""
    if key == "pk_window":
        if len(got) != len(expected):
            return False, f"{len(got)} bands, expected {len(expected)}"
        for (glo, ghi), (elo, ehi) in zip(got, expected):
            if grid:  # the app's band is read on its grid: inside the true band, by at most one step at each end
                ok = elo - tol <= glo <= elo + TOL["pk_grid"] + tol and ehi - TOL["pk_grid"] - tol <= ghi <= ehi + tol
            else:
                ok = close(glo, elo, tol) and close(ghi, ehi, tol)
            if not ok:
                return False, f"[{fmt(glo)}, {fmt(ghi)}]"
        return True, ""
    return close(got, expected, tol), ""


# ----------------------------------------------------------------------------------------------------------------
def compare(case, app, ref, rep: Report):
    cid = case["id"]
    add = lambda *a, **k: rep.add(cid, *a, **k)
    opts = ref["options"]

    # --- the app ran cleanly -----------------------------------------------------------------------------------
    add("app", "no script errors in the page", not app["pageErrors"], app=app["pageErrors"] or "none")
    expected_errors = case.get("expect_errors", [])
    add("app", "no input errors", [e["msg"] for e in app["errors"]] == expected_errors, app=[e["msg"] for e in app["errors"]] or "none")
    add("app", "results computed", bool(app["ok"]), app=app["ok"])
    add("app", "options read", app["options"] == opts, app=app["options"], ref=opts)
    if not app["ok"]:
        return
    tie = app.get("tie")
    shown = "none (level)" if tie else opts[app["pointLeader"]]
    add("app", "panel names the leader", app["dom"]["leader"] == shown, app=app["dom"]["leader"], ref=shown)

    # --- likely values -----------------------------------------------------------------------------------------
    for k, o in enumerate(opts):
        add("fold-back", f"value of '{o}'", close(app["point"][k], ref["point"][k], TOL["point_rel"] * max(1, abs(ref["point"][k]))),
            app=app["point"][k], ref=ref["point"][k])
    add("fold-back", "leader on likely values", app["pointLeader"] == ref["pointLeader"], app=opts[app["pointLeader"]], ref=opts[ref["pointLeader"]])
    for name, v in ref["scope"].items():
        if name in app["scope"]:
            add("fold-back", f"number '{name}'", close(app["scope"][name], v, TOL["point_rel"] * max(1, abs(v))), app=app["scope"][name], ref=v)

    # --- switch points -----------------------------------------------------------------------------------------
    for name, rb in ref["breakevens"].items():
        ab = app["breakevens"].get(name)
        if not add("switch points", f"'{name}' is swept", ab is not None, app="missing" if ab is None else "yes"):
            continue
        lo, hi = rb["range"]
        w = hi - lo
        same_window = close(ab["range"][0], lo, 1e-9 * max(1, abs(w))) and close(ab["range"][1], hi, 1e-9 * max(1, abs(w)))
        add("switch points", f"'{name}' sweep from {fmt(lo)} to {fmt(hi)}", same_window, app=ab["range"], ref=rb["range"])
        ac, rc = ab["crossings"], rb["crossings"]
        if not add("switch points", f"'{name}': number of switch points", len(ac) == len(rc), app=len(ac), ref=len(rc),
                   note="" if len(ac) == len(rc) else f"app {[fmt(c['at']) for c in ac]}, reference {[fmt(c['at']) for c in rc]}"):
            continue
        for a, r in zip(ac, rc):
            label = f"'{name}': {opts[r['from']]} -> {opts[r['to']]}"
            add("switch points", label + " at", close(a["at"], r["at"], TOL["switch_rel"] * w + 1e-12), app=a["at"], ref=r["at"])
            add("switch points", label + " between the same options", (a["from"], a["to"]) == (r["from"], r["to"]),
                app=(opts[a["from"]], opts[a["to"]]), ref=(opts[r["from"]], opts[r["to"]]))
            add("switch points", label + " inside the range", a["inRange"] == r["inRange"], app=a["inRange"], ref=r["inRange"])

    # --- plausible worlds (same random numbers) ----------------------------------------------------------------
    asim, rsim = app["sim"], ref["sim"]
    spread = max([o["q975"] - o["q025"] for o in rsim["opts"]] + [1.0])
    for name, head in asim.get("drawsHead", {}).items():
        rng = ref["ranges"][name]
        width = rng["U"] - rng["L"]
        mine = ref["drawsHead"][name][:len(head)]
        worst = max(abs(a - b) for a, b in zip(head, mine))
        add("worlds", f"random stream for '{name}' in step", worst <= TOL["draw_rel"] * width, app=head[:3], ref=mine[:3],
            note="if this fails, the app's random numbers changed; the averages below are then compared only to the independent stream")
    n = asim["N"]
    add("worlds", "worlds whose chances don't fit", abs(asim["badWorlds"] - rsim["badWorlds"]) <= max(2, TOL["bad_worlds"] * n), app=asim["badWorlds"], ref=rsim["badWorlds"])
    for k, o in enumerate(opts):
        ao, ro = asim["opts"][k], rsim["opts"][k]
        add("worlds", f"'{o}' average", close(ao["mean"], ro["mean"], TOL["mean_scale"] * spread), app=ao["mean"], ref=ro["mean"])
        add("worlds", f"'{o}' 2.5% point", close(ao["q025"], ro["q025"], TOL["quantile_scale"] * spread), app=ao["q025"], ref=ro["q025"])
        add("worlds", f"'{o}' 97.5% point", close(ao["q975"], ro["q975"], TOL["quantile_scale"] * spread), app=ao["q975"], ref=ro["q975"])
        add("worlds", f"'{o}' best in", close(ao["pBest"], ro["pBest"], TOL["share"]), app=ao["pBest"], ref=ro["pBest"])
    add("worlds", "leader on average", asim["meanLeader"] == rsim["meanLeader"], app=opts[asim["meanLeader"]], ref=opts[rsim["meanLeader"]])
    add("worlds", "EVPI (knowing everything)", close(asim["evpi"], rsim["evpi"], 1e-3 * abs(rsim["evpi"]) + TOL["mean_scale"] * spread), app=asim["evpi"], ref=rsim["evpi"])
    ap, rp = app.get("pair"), ref.get("pair")
    if rp:
        add("head to head", "leader and challenger", (ap["a"], ap["b"]) == (rp["a"], rp["b"]), app=(opts[ap["a"]], opts[ap["b"]]), ref=(opts[rp["a"]], opts[rp["b"]]))
        if (ap["a"], ap["b"]) == (rp["a"], rp["b"]):
            add("head to head", "challenger beats leader in", close(ap["pB"], rp["pB"], TOL["share"]), app=ap["pB"], ref=rp["pB"])
            add("head to head", "average difference", close(ap["meanDiff"], rp["meanDiff"], TOL["mean_scale"] * spread), app=ap["meanDiff"], ref=rp["meanDiff"])
            add("head to head", "difference 2.5% point", close(ap["q025"], rp["q025"], TOL["quantile_scale"] * spread), app=ap["q025"], ref=rp["q025"])
            add("head to head", "difference 97.5% point", close(ap["q975"], rp["q975"], TOL["quantile_scale"] * spread), app=ap["q975"], ref=rp["q975"])

    # --- plausible worlds (independent random numbers, 200,000 worlds) -----------------------------------------
    ind = ref["independent"]
    if asim["hasRanges"]:
        for k, o in enumerate(opts):
            ao, io = asim["opts"][k], ind["opts"][k]
            se = math.sqrt(ao["sd"] ** 2 / n + io["sd"] ** 2 / ind["N"])
            add("independent stream", f"'{o}' average", abs(ao["mean"] - io["mean"]) <= TOL["independent_se"] * se + 1e-9, app=ao["mean"], ref=io["mean"], note=f"4 SE = {fmt(4 * se)}")
            p = io["pBest"]
            se = math.sqrt(max(p * (1 - p), 1 / ind["N"]) * (1 / n + 1 / ind["N"]))
            add("independent stream", f"'{o}' best in", abs(ao["pBest"] - p) <= TOL["independent_se"] * se, app=ao["pBest"], ref=p, note=f"4 SE = {fmt(4 * se)}")
        p = ind["badWorlds"] / ind["N"]
        se = math.sqrt(max(p * (1 - p), 1 / ind["N"]) * (1 / n + 1 / ind["N"]))
        add("independent stream", "share of worlds whose chances don't fit", abs(asim["badWorlds"] / n - p) <= TOL["independent_se"] * se, app=asim["badWorlds"] / n, ref=p)

    # --- what is worth finding out -----------------------------------------------------------------------------
    for name, rv in ref["evppi"].items():
        av = app["evppi"].get(name)
        add("value of information", f"EVPPI '{name}' (same estimator)", close(av, rv, TOL["evppi_rel"] * rv + TOL["mean_scale"] * spread), app=av, ref=rv)
        ex = ref["evppi_exact"][name]
        tol = max(TOL["evppi_exact_rel"] * ex, TOL["evppi_exact_evpi"] * rsim["evpi"], 1.0)
        add("value of information", f"EVPPI '{name}' vs near-exact", close(av, ex, tol), app=av, ref=ex, level="WARN",
            note=f"tolerance {fmt(tol)}; the cubic smoother is an approximation")
    if len(ref["evppi_exact"]) > 1:
        ex = sorted(ref["evppi_exact"].items(), key=lambda kv: -kv[1])
        # rank only when the leader is clear and material: the app hides values that round to zero
        if ex[0][1] > 1.2 * ex[1][1] and ex[0][1] >= max(1.0, TOL["evppi_exact_evpi"] * rsim["evpi"]):
            top = max(app["evppi"].items(), key=lambda kv: kv[1])[0]
            add("value of information", "the number most worth pinning down", top == ex[0][0], app=top, ref=ex[0][0], level="WARN")

    # --- diagnostic month --------------------------------------------------------------------------------------
    rd, ad = ref.get("diag"), app.get("diag")
    if rd:
        if add("diagnostic month", "computed", bool(ad) and "error" not in ad, app=ad):
            for f in ("evsi", "cost", "enbs", "now"):
                add("diagnostic month", f, close(ad[f], rd[f], 1e-3 * abs(rd[f]) + TOL["mean_scale"] * spread), app=ad[f], ref=rd[f])
            for f in ("pos", "neg"):
                add("diagnostic month", f"chance of a {'good' if f == 'pos' else 'bad'} month", close(ad[f]["P"], rd[f]["P"], 1e-4), app=ad[f]["P"], ref=rd[f]["P"])
                add("diagnostic month", f"choice after a {'good' if f == 'pos' else 'bad'} month", ad[f]["bestIdx"] == rd[f]["bestIdx"], app=opts[ad[f]["bestIdx"]], ref=opts[rd[f]["bestIdx"]])
            add("diagnostic month", "the month could change the decision", ad["changes"] == rd["changes"], app=ad["changes"], ref=rd["changes"])
            for f in ("postPos", "postNeg", "pGood"):
                add("diagnostic month", f, close(ad[f], rd[f], TOL["post"]), app=ad[f], ref=rd[f])
            ok, note = matches("pk_window", ad["pkWindows"], rd["pkWindows"], 1e-9, grid=True)
            add("diagnostic month", "band of the chance where the month pays", ok, app=ad["pkWindows"], ref=rd["pkWindows"], note=note)

    # --- hand-derived numbers (Andrew's algebra), checked on both sides ----------------------------------------
    for h in case.get("hand_checks", []):
        tol = h.get("tol", 0)
        for side, res in (("reference", ref), ("app", app)):
            got = metric(res, h["metric"])
            ok, note = matches(h["metric"], got, h["expected"], tol, grid=(side == "app"))
            add("hand-derived", f"{h['metric']} ({side})", ok, app=got if side == "app" else None, ref=got if side == "reference" else None,
                expected=h["expected"], note=(note + " " if note else "") + h.get("why", ""))
    for h in case.get("documented", []):
        got = metric(app, h["metric"])
        ok, note = matches(h["metric"], got, h["expected"], h.get("tol", 0))
        add("README claims", h["metric"], ok, app=got, expected=h["expected"], note=h.get("why", ""))
    for h in case.get("article", []):
        rep.add(cid, "article (context)", h["metric"], False, app=metric(app, h["metric"]), expected=h["value"], level="INFO", note=h.get("note", ""))


# ----------------------------------------------------------------------------------------------------------------
def write_report(cases, app, ref, rep: Report, path: Path, seconds: float):
    c = rep.count()
    lines = [
        "# Foldback test report", "",
        f"{len(cases)} cases, {sum(c.values())} checks: **{c['PASS']} pass, {c['FAIL']} fail, {c['WARN']} warn**, {c['INFO']} for context. ({seconds:.0f} s)", "",
        "| Case | Pass | Fail | Warn | Leader on likely values | Leader on average |", "|---|---|---|---|---|---|",
    ]
    for case in cases:
        k = rep.count(case["id"])
        a = app[case["id"]]
        lead = a["options"][a["pointLeader"]] if a.get("ok") else "—"
        mlead = a["options"][a["sim"]["meanLeader"]] if a.get("ok") else "—"
        lines.append(f"| {case['id']} | {k['PASS']} | {k['FAIL']} | {k['WARN']} | {lead} | {mlead} |")
    for case in cases:
        cid = case["id"]
        a, r = app[cid], ref[cid]
        lines += ["", f"## {cid}: {case['title']}", "", case["story"], ""]
        lines += ["| Option | Likely value (app) | Average (app) | Best in (app) | Best in (reference) |", "|---|---|---|---|---|"]
        for k, o in enumerate(r["options"]):
            ao = a["sim"]["opts"][k] if a.get("ok") else {}
            lines.append(f"| {o} | {fmt(a['point'][k])} | {fmt(ao.get('mean'))} | {fmt(ao.get('pBest'))} | {fmt(r['sim']['opts'][k]['pBest'])} |")
        if r["evppi"]:
            lines += ["", "| Worth pinning down | App | Same estimator (reference) | Near-exact (reference) |", "|---|---|---|---|"]
            for name in sorted(r["evppi_exact"], key=lambda n: -r["evppi_exact"][n]):
                lines.append(f"| {name} | {fmt(a['evppi'].get(name))} | {fmt(r['evppi'][name])} | {fmt(r['evppi_exact'][name])} |")
        rows = [x for x in rep.rows if x["case"] == cid]
        bad = [x for x in rows if x["status"] in ("FAIL", "WARN")]
        lines += ["", f"**Checks:** {sum(x['status'] == 'PASS' for x in rows)} pass, {sum(x['status'] == 'FAIL' for x in rows)} fail, {sum(x['status'] == 'WARN' for x in rows)} warn."]
        if bad:
            lines += ["", "| Status | Section | Check | App | Reference | Expected | Note |", "|---|---|---|---|---|---|---|"]
            lines += [f"| {x['status']} | {x['section']} | {x['what']} | {fmt(x['app'])} | {fmt(x['ref'])} | {fmt(x['expected'])} | {x['note']} |" for x in bad]
        hand = [x for x in rows if x["section"] in ("hand-derived", "README claims")]
        if hand:
            lines += ["", "<details><summary>Hand-derived and documented numbers</summary>", "", "| Status | Check | Got | Expected | Why |", "|---|---|---|---|---|"]
            lines += [f"| {x['status']} | {x['what']} | {fmt(x['app'] if x['app'] is not None else x['ref'])} | {fmt(x['expected'])} | {x['note']} |" for x in hand]
            lines += ["", "</details>"]
        info = [x for x in rows if x["status"] == "INFO"]
        if info:
            lines += ["", "Against the article's published figures (context only, the article's inputs differ):", "", "| Result | App | Article | Note |", "|---|---|---|---|"]
            lines += [f"| {x['what']} | {fmt(x['app'])} | {fmt(x['expected'])} | {x['note']} |" for x in info]
    path.write_text("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("only", nargs="*", help="run only cases whose file name starts with one of these")
    ap.add_argument("--app-json", help="use app results saved by an earlier run instead of running the browser")
    ap.add_argument("--out", default=str(HERE / "output"), help="folder for the report and raw results")
    args = ap.parse_args()

    files = sorted((HERE / "cases").glob("*.json"))
    if args.only:
        files = [f for f in files if any(f.name.startswith(o) for o in args.only)]
    if not files:
        sys.exit("No cases matched.")
    cases = [json.loads(f.read_text()) for f in files]
    t0 = time.time()
    app_raw = json.loads(Path(args.app_json).read_text()) if args.app_json else run_app(files)
    app = {k: normalize_app(v) for k, v in app_raw.items()}
    ref = {}
    for c in cases:
        print(f"reference: {c['id']}", file=sys.stderr)
        ref[c["id"]] = reference.run_case(c)

    rep = Report()
    for c in cases:
        if c["id"] not in app:
            rep.add(c["id"], "app", "case ran in the app", False, note="no result")
            continue
        compare(c, app[c["id"]], ref[c["id"]], rep)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "app_results.json").write_text(json.dumps(app_raw, indent=1))
    (out / "reference_results.json").write_text(json.dumps(ref, indent=1, default=float))
    write_report(cases, app, ref, rep, out / "report.md", time.time() - t0)

    for c in cases:
        k = rep.count(c["id"])
        print(f"{c['id']:<40} {k['PASS']:>4} pass {k['FAIL']:>3} fail {k['WARN']:>3} warn")
    for x in rep.rows:
        if x["status"] in ("FAIL", "WARN"):
            print(f"  {x['status']} {x['case']} | {x['section']} | {x['what']} | app {fmt(x['app'])} | ref {fmt(x['ref'])} | expected {fmt(x['expected'])} | {x['note']}")
    k = rep.count()
    print(f"\n{k['PASS']} pass, {k['FAIL']} fail, {k['WARN']} warn. Report: {out / 'report.md'}")
    sys.exit(1 if k["FAIL"] else 0)


if __name__ == "__main__":
    main()
