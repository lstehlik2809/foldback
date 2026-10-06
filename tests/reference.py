"""Independent reference implementation of the method in Andrew Marritt's "Should you replace Sam?".

It reads a test case (the app's own saved-tree format) and computes, with its own code:

  * fold-back at the likely values (each chance point = probability-weighted average of what follows it),
  * switch points: the value of each number at which the leading option changes, others held at likely values,
  * probabilistic sensitivity analysis (PSA): each range is a Beta curve between Low and High with its median at
    Likely and a + b = 6, drawn 10,000 times; each world folds the tree back once,
  * how often each option is best, the head-to-head between the leader and its main challenger, EVPI,
  * EVPPI two ways: the regression estimator the app uses (cubic smoother, Strong, Oakley & Brennan 2014 style),
    and a near-exact conditional-expectation estimator used to judge the regression's accuracy,
  * the diagnostic month: preposterior value of a yes/no signal on one chance (EVSI), and the band of that chance in
    which the signal pays (Pauker & Kassirer 1980 threshold approach).

Nothing here is copied from the app's JavaScript. Two things are deliberately shared so the comparison is like for
like rather than a comparison of random noise:

  * the random numbers: the app's uniform stream (FNV-1a hash of "seed|in:<key>" seeding mulberry32) is reproduced,
    so both sides see the same worlds ("common random numbers"). The transform from uniforms to values is our own
    (exact inverse Beta from SciPy, not the app's 2,000-point grid). A separate, fully independent NumPy stream with
    200,000 worlds checks the app's averages within Monte Carlo error.
  * UI conventions that are choices, not method: how far each number is swept for switch points, that the leader is
    the option with the highest value at the likely values, that ties go to the earlier option, and that a world
    whose chances do not fit (a group over 100%) is still counted, with the empty outcome getting max(0, rest).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np
from scipy import optimize, special

N_WORLDS = 10_000          # the app's number of plausible worlds
N_INDEPENDENT = 200_000    # worlds for the independent-stream check
SWEEP_POINTS = 4_801       # switch-point grid (the app uses 241); a finer grid can only find more switch points
EXACT_EVPPI_POINTS = 400   # quantile points for the conditional-expectation EVPPI
PK_POINTS = 20_001         # grid for the diagnostic-month band before the edges are refined

# ---------------------------------------------------------------------------------------------------------------
# Formula language: numbers with k / m / % suffixes, names, + - * / ^, comparisons, && || !, and a few functions.
# ---------------------------------------------------------------------------------------------------------------
_TOKEN = re.compile(r"\s*(?:(?P<num>(?:\d[\d_]*(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)(?P<suf>%|[kKmM](?![A-Za-z0-9_]))?"
                    r"|(?P<id>[A-Za-z_][A-Za-z0-9_]*)|(?P<op><=|>=|==|!=|&&|\|\||[-+*/^(),<>!]))")


def _tokens(src: str):
    out, pos, src = [], 0, str(src)
    while pos < len(src):
        if src[pos:].strip() == "":
            break
        m = _TOKEN.match(src, pos)
        if not m or m.end() == pos:
            raise ValueError(f"cannot read {src[pos:]!r}")
        if m.group("num") is not None:
            v = float(m.group("num").replace("_", ""))
            suf = m.group("suf") or ""
            v *= {"%": 0.01, "k": 1e3, "K": 1e3, "m": 1e6, "M": 1e6}.get(suf, 1.0)
            out.append(("n", v))
        elif m.group("id") is not None:
            out.append(("id", m.group("id")))
        else:
            out.append(("op", m.group("op")))
        pos = m.end()
    return out


def _js_round(x):
    return np.floor(np.asarray(x, dtype=float) + 0.5)


def _zbar(sr):
    """Mean standardised predictor score of those hired when the top `sr` share is selected (Brogden/Naylor-Shine)."""
    sr = np.asarray(sr, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.exp(-0.5 * special.ndtri(1 - sr) ** 2) / math.sqrt(2 * math.pi) / sr
    return np.where((sr > 0) & (sr < 1), out, np.nan)


def _fold(f):
    return lambda *a: f(a[0], a[1]) if len(a) == 2 else _fold(f)(f(a[0], a[1]), *a[2:]) if len(a) > 2 else np.asarray(a[0], float)


FUNCS = {
    "min": _fold(np.minimum), "max": _fold(np.maximum), "abs": np.abs, "sqrt": np.sqrt, "exp": np.exp,
    "log": np.log, "ln": np.log, "log10": np.log10, "pow": np.power, "round": _js_round, "floor": np.floor,
    "ceil": np.ceil, "if": lambda c, a, b: np.where(np.asarray(c) != 0, a, b),
    "clamp": lambda x, lo, hi: np.minimum(hi, np.maximum(lo, x)),
    "zbar": _zbar, "normcdf": special.ndtr, "norminv": special.ndtri,
}


class Formula:
    """Parses a formula once into a closure; evaluates with scalars or NumPy arrays."""

    def __init__(self, src: str, known: set[str] | None = None):
        self.src = "" if src is None else str(src)
        self.names: set[str] = set()
        if self.src.strip() == "":
            self.fn = lambda env: 0.0
            return
        self.t, self.p, self.known = _tokens(self.src), 0, known
        self.fn = self._or()
        if self.p != len(self.t):
            raise ValueError(f"unexpected {self.t[self.p][1]!r} in {self.src!r}")
        del self.t

    def __call__(self, env):
        return self.fn(env)

    def _peek(self):
        return self.t[self.p][1] if self.p < len(self.t) else None

    def _eat(self, v=None):
        if self.p >= len(self.t) or (v is not None and self.t[self.p][1] != v):
            raise ValueError(f"expected {v!r} in {self.src!r}")
        self.p += 1
        return self.t[self.p - 1]

    def _bin(self, nxt, ops):
        left = nxt()
        while self._peek() in ops:
            op = self._eat()[1]
            right = nxt()
            left = (lambda f, l, r: (lambda e: f(l(e), r(e))))(ops[op], left, right)
        return left

    def _or(self):
        return self._bin(self._and, {"||": lambda a, b: ((np.asarray(a) != 0) | (np.asarray(b) != 0)).astype(float)})

    def _and(self):
        return self._bin(self._cmp, {"&&": lambda a, b: ((np.asarray(a) != 0) & (np.asarray(b) != 0)).astype(float)})

    def _cmp(self):
        ops = {"<": np.less, ">": np.greater, "<=": np.less_equal, ">=": np.greater_equal, "==": np.equal, "!=": np.not_equal}
        return self._bin(self._add, {k: (lambda f: lambda a, b: f(a, b).astype(float))(f) for k, f in ops.items()})

    def _add(self):
        return self._bin(self._mul, {"+": np.add, "-": np.subtract})

    def _mul(self):
        return self._bin(self._unary, {"*": np.multiply, "/": lambda a, b: np.divide(a, b)})

    def _unary(self):
        op = self._peek()
        if op in ("-", "+", "!"):
            self._eat()
            inner = self._unary()
            if op == "-":
                return lambda e: -inner(e)
            if op == "!":
                return lambda e: (np.asarray(inner(e)) == 0).astype(float)
            return inner
        return self._power()

    def _power(self):
        base = self._prim()
        if self._peek() == "^":
            self._eat()
            ex = self._unary()
            return lambda e: np.power(np.asarray(base(e), float), ex(e))
        return base

    def _prim(self):
        if self.p >= len(self.t):
            raise ValueError(f"incomplete formula {self.src!r}")
        kind, v = self.t[self.p]
        self.p += 1
        if kind == "n":
            return lambda e, v=v: v
        if kind == "op" and v == "(":
            inner = self._or()
            self._eat(")")
            return inner
        if kind == "id":
            if self._peek() == "(":
                if v not in FUNCS:
                    raise ValueError(f"unknown function {v!r}")
                self._eat("(")
                args = []
                if self._peek() != ")":
                    args.append(self._or())
                    while self._peek() == ",":
                        self._eat()
                        args.append(self._or())
                self._eat(")")
                f = FUNCS[v]
                return lambda e, f=f, args=args: f(*[a(e) for a in args])
            if v in ("true", "false"):
                return lambda e, c=float(v == "true"): c
            if self.known is not None and v not in self.known:
                raise ValueError(f"unknown name {v!r}")
            self.names.add(v)
            return lambda e, v=v: e[v]
        raise ValueError(f"unexpected {v!r} in {self.src!r}")


def constant(src) -> float:
    """The value of a field that holds a plain number or a constant formula, else NaN."""
    if src is None or str(src).strip() == "":
        return math.nan
    try:
        return float(Formula(src, known=set())({}))
    except (ValueError, KeyError):
        return math.nan


# A range typed into a field: "-37k to -25k ~-30k", "20–45% ~30%". A suffix on the high end carries to the others.
_NUM = r"-?(?:\d[\d,]*(?:\.\d+)?|\.\d+)\s*[kKmM%]?"
_RANGE = re.compile(rf"^\s*({_NUM})\s*(?:to|–|—|\.\.|-)\s*({_NUM})\s*(?:[,;(]?\s*(?:~|likely|mid)\s*({_NUM})\s*\)?)?\s*$", re.I)


def _plain(s: str) -> float:
    s = re.sub(r"[\s,]", "", s)
    mult = {"k": 1e3, "m": 1e6, "%": 0.01}.get(s[-1].lower(), 1.0)
    return float(s[:-1] if mult != 1.0 else s) * mult


def parse_range(src):
    m = _RANGE.match(str(src or ""))
    if not m:
        return None
    a, b, c = m.group(1), m.group(2), m.group(3)
    suffix = lambda t: t.strip()[-1] if t.strip()[-1] in "kKmM%" else ""
    if suffix(b) and not suffix(a):
        a += suffix(b)
    if c and suffix(b) and not suffix(c):
        c += suffix(b)
    lo, hi = sorted((_plain(a), _plain(b)))
    return lo, hi, (_plain(c) if c else (lo + hi) / 2)


# ---------------------------------------------------------------------------------------------------------------
# Elicited ranges: a Beta curve stretched between Low and High, median at Likely, a + b = 6 (PERT-style spread)
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class BetaRange:
    L: float
    U: float
    m: float
    a: float = field(init=False)
    b: float = field(init=False)

    def __post_init__(self):
        if not (self.L < self.m < self.U):
            raise ValueError("needs Low < Likely < High")
        zm = (self.m - self.L) / (self.U - self.L)
        self.a = optimize.brentq(lambda a: special.betainc(a, 6 - a, zm) - 0.5, 1e-9, 6 - 1e-9, xtol=1e-15, rtol=1e-15)
        self.b = 6 - self.a

    def ppf(self, u):
        return self.L + (self.U - self.L) * special.betaincinv(self.a, self.b, u)

    def cdf(self, x):
        return special.betainc(self.a, self.b, (np.asarray(x) - self.L) / (self.U - self.L))

    @property
    def mean(self):
        return self.L + (self.U - self.L) * self.a / 6


# The app's uniform stream, reproduced bit for bit (32-bit FNV-1a of "seed|key", then mulberry32).
_M32 = 0xFFFFFFFF


def _fnv1a(s: str) -> int:
    h, data = 2166136261, s.encode("utf-16-le")  # UTF-16 code units, as JavaScript's charCodeAt
    for i in range(0, len(data), 2):
        h ^= data[i] | data[i + 1] << 8
        h = (h * 16777619) & _M32
    return h


def app_uniforms(seed: str, key: str, n: int) -> np.ndarray:
    a = _fnv1a(f"{seed}|{key}")
    out = np.empty(n)
    for i in range(n):
        a = (a + 0x6D2B79F5) & _M32
        t = ((a ^ (a >> 15)) * (1 | a)) & _M32
        t = ((t + (((t ^ (t >> 7)) * (61 | t)) & _M32)) & _M32) ^ t
        x = ((t ^ (t >> 14)) & _M32) / 4294967296
        out[i] = x if x > 0 else 1e-12
    return out


# ---------------------------------------------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class Node:
    id: str
    label: str
    value: Formula
    prob: Formula | None            # None = takes the rest of its group
    children: list["Node"]


@dataclass
class Model:
    options: list[Node]
    labels: list[str]
    fixed: dict[str, float]                     # numbers with one value
    ranges: dict[str, BetaRange]                # numbers with a range (shared or typed into the tree)
    stream_keys: dict[str, str]                 # range name -> key of its uniform stream
    calcs: list[tuple[str, Formula]]            # numbers defined by a formula, in dependency order
    prob_names: set[str]
    order: list[str]                            # inputs in the order they were declared


def _ids(src) -> list[str]:
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*", str(src or ""))


def build_model(state: dict) -> Model:
    prob_names: set[str] = set()

    def walk_p(n):
        prob_names.update(_ids(n.get("prob")))
        for c in n.get("branches", []):
            walk_p(c)

    for o in state["options"]:
        for b in o.get("branches", []):
            walk_p(b)

    fixed, ranges, keys, order, calc_src = {}, {}, {}, [], {}
    for v in state["numbers"]:
        name = v["name"].strip()
        has_range = str(v.get("low", "")).strip() != "" or str(v.get("high", "")).strip() != ""
        likely = constant(v.get("likely"))
        if has_range:
            lo, hi = constant(v["low"]), constant(v["high"])
            ranges[name] = BetaRange(lo, hi, likely if math.isfinite(likely) else (lo + hi) / 2)
            keys[name] = "n:" + name
            order.append(name)
        elif math.isfinite(likely):
            fixed[name] = likely
            order.append(name)
        else:
            calc_src[name] = v["likely"]

    def node(n, opt_label, is_option=False):
        fields = {}
        for f in ("value", "prob"):
            raw = n.get(f, "")
            r = parse_range(raw)
            if r and not (f == "prob" and is_option):
                nm = f"u_{n['id']}_{f}"
                ranges[nm] = BetaRange(r[0], r[1], r[2])
                keys[nm] = nm
                order.append(nm)
                if f == "prob":
                    prob_names.add(nm)
                fields[f] = nm
            else:
                fields[f] = raw
        kids = [node(c, n.get("label", "")) for c in n.get("branches", [])]
        prob = None if is_option or str(fields["prob"] or "").strip().lower() in ("", "rest") else Formula(fields["prob"])
        return Node(n["id"], n.get("label", ""), Formula(fields["value"]), prob, kids)

    options = [node(o, o.get("label", ""), is_option=True) for o in state["options"]]

    # numbers defined by formulas: order them so that what they use comes first
    known = set(fixed) | set(ranges)
    calcs, pending = [], dict(calc_src)
    while pending:
        ready = [k for k, src in pending.items() if all(d in known or d not in calc_src for d in _ids(src) if d not in FUNCS)]
        if not ready:
            raise ValueError(f"circular formulas: {sorted(pending)}")
        for k in ready:
            calcs.append((k, Formula(pending.pop(k))))
            known.add(k)
    return Model(options, [o.get("label", "") for o in state["options"]], fixed, ranges, keys, calcs, prob_names, order)


def scope(model: Model, draws: dict | None = None, overrides: dict | None = None) -> dict:
    env = dict(model.fixed)
    env.update({k: r.m for k, r in model.ranges.items()})
    if draws:
        env.update(draws)
    if overrides:
        env.update(overrides)
    for name, f in model.calcs:
        env[name] = f(env)
    return env


def ev(node: Node, env: dict, n: int, flags: dict) -> np.ndarray:
    """Folds one node back: its value plus the probability-weighted average of its outcomes. `flags` gathers, per
    world, chances outside 0-100% or a group that does not add up to 100%."""
    val = np.broadcast_to(np.asarray(node.value(env), float), (n,)).copy()
    if not node.children:
        return val
    total, probs = np.zeros(n), []
    has_rest = any(c.prob is None for c in node.children)
    for c in node.children:
        if c.prob is None:
            probs.append(None)
            continue
        p = np.broadcast_to(np.asarray(c.prob(env), float), (n,))
        flags["bad"] |= ~np.isfinite(p) | (p < -1e-9) | (p > 1 + 1e-9)
        total = total + p
        probs.append(p)
    flags["bad"] |= total > 1 + 1e-9
    if not has_rest:
        flags["bad"] |= np.abs(total - 1) > 1e-6
    out = np.zeros(n)
    for c, p in zip(node.children, probs):
        if p is None:
            p = np.maximum(0.0, 1 - total)
        live = p != 0  # an outcome with no chance is not followed (and its problems are not counted)
        if not live.any():
            continue
        sub = {"bad": np.zeros(n, bool)}
        child = ev(c, env, n, sub)
        flags["bad"] |= sub["bad"] & live
        out += np.where(live, p * np.where(live, child, 0.0), 0.0)
    return val + out


def option_values(model: Model, env: dict, n: int):
    flags = {"bad": np.zeros(n, bool)}
    vals = np.vstack([ev(o, env, n, flags) for o in model.options])
    return vals, flags["bad"]


def point_values(model: Model, overrides: dict | None = None):
    env = scope(model, overrides=overrides)
    vals, bad = option_values(model, env, 1)
    return vals[:, 0], bool(bad[0]), env


# ---------------------------------------------------------------------------------------------------------------
# Switch points
# ---------------------------------------------------------------------------------------------------------------
def sweep_window(model: Model, name: str):
    if name in model.prob_names:
        return 0.0, 1.0
    if name in model.ranges:
        r = model.ranges[name]
        w = r.U - r.L
        return r.L - 0.75 * w, r.U + 0.75 * w
    v = model.fixed[name]
    return (-1.0, 1.0) if v == 0 else ((0.0, 3 * v) if v > 0 else (3 * v, 0.0))


def switch_points(model: Model, name: str):
    lo, hi = sweep_window(model, name)
    xs = np.linspace(lo, hi, SWEEP_POINTS)
    env = scope(model, overrides={name: xs})
    vals, bad = option_values(model, env, len(xs))
    ok = ~bad & np.all(np.isfinite(vals), axis=0)
    lead = np.argmax(vals, axis=0)

    def diff(t, a, b):
        v, _, _ = point_values(model, {name: t})
        return v[b] - v[a]

    out, prev = [], None
    for i in range(len(xs)):
        if not ok[i]:
            prev = None
            continue
        if prev is not None and lead[i] != lead[prev]:
            a, b, x0, x1 = lead[prev], lead[i], xs[prev], xs[i]
            for _ in range(100):
                mid = (x0 + x1) / 2
                if diff(mid, a, b) > 0:
                    x1 = mid
                else:
                    x0 = mid
            at = (x0 + x1) / 2
            r = model.ranges.get(name)
            out.append({"at": at, "from": int(a), "to": int(b), "inRange": bool(r and r.L <= at <= r.U)})
        prev = i
    return {"range": [lo, hi], "crossings": out}


# ---------------------------------------------------------------------------------------------------------------
# Plausible worlds
# ---------------------------------------------------------------------------------------------------------------
def crn_draws(model: Model, seed: str, n: int = N_WORLDS) -> dict:
    return {k: r.ppf(app_uniforms(seed, "in:" + model.stream_keys[k], n)) for k, r in model.ranges.items()}


def independent_draws(model: Model, n: int = N_INDEPENDENT, seed: int = 20260923) -> dict:
    rng = np.random.Generator(np.random.PCG64(seed))
    return {k: r.L + (r.U - r.L) * rng.beta(r.a, r.b, n) for k, r in sorted(model.ranges.items())}


def worlds(model: Model, draws: dict, n: int):
    env = scope(model, draws=draws)
    vals, bad = option_values(model, env, n)
    return vals, bad, env


def summarize(vals: np.ndarray, point: np.ndarray):
    K, n = vals.shape
    best = np.argmax(vals, axis=0)
    means = vals.mean(axis=1)
    opts = [{"mean": float(means[k]), "q025": float(np.quantile(vals[k], 0.025)), "q975": float(np.quantile(vals[k], 0.975)),
             "pBest": float(np.mean(best == k)), "sd": float(vals[k].std(ddof=1))} for k in range(K)]
    evpi = float(vals.max(axis=0).mean() - means.max())
    order = sorted(range(K), key=lambda k: -point[k])
    pair = None
    if K > 1:
        a = order[0]
        pbs = [(b, float(np.mean(vals[b] - vals[a] > 0))) for b in order[1:]]
        threat = pbs[0]
        for b, pb in pbs[1:]:
            if pb > threat[1]:
                threat = (b, pb)
        d = vals[threat[0]] - vals[a]
        pair = {"a": a, "b": threat[0], "threat": threat[0], "pB": threat[1], "meanDiff": float(d.mean()),
                "q025": float(np.quantile(d, 0.025)), "q975": float(np.quantile(d, 0.975))}
    return {"opts": opts, "evpi": evpi, "meanLeader": int(np.argmax(means)), "order": order}, pair


# ---------------------------------------------------------------------------------------------------------------
# Value of information
# ---------------------------------------------------------------------------------------------------------------
def evppi_regression(vals: np.ndarray, x: np.ndarray) -> float:
    """Regression EVPPI (Strong, Oakley & Brennan 2014) with a cubic polynomial smoother, as the app describes it:
    regress each option's value relative to the first option on the one number, then E[max fitted] - max E."""
    z = (x - x.mean()) / (x.std() or 1.0)
    X = np.vander(z, 4, increasing=True)
    rel = vals - vals[0]
    fitted = np.vstack([X @ np.linalg.lstsq(X, y, rcond=None)[0] for y in rel])
    return max(0.0, float(fitted.max(axis=0).mean() - rel.mean(axis=1).max()))


def evppi_exact(model: Model, draws: dict, name: str, n: int) -> float:
    """Near-exact single-number EVPPI: fix the number at each of 400 equal-probability points, average every option
    over the same worlds for all the other numbers (conditional expectation), take the best option at each point."""
    r = model.ranges[name]
    us = (np.arange(EXACT_EVPPI_POINTS) + 0.5) / EXACT_EVPPI_POINTS
    cond = []
    for t in r.ppf(us):
        d = dict(draws)
        d[name] = np.full(n, t)
        vals, _, _ = worlds(model, d, n)
        cond.append(vals.mean(axis=1))
    cond = np.array(cond)
    return max(0.0, float(cond.max(axis=1).mean() - cond.mean(axis=0).max()))


def diagnostic(model: Model, draws: dict, vals: np.ndarray, diag: dict, n: int):
    """Preposterior value of a yes/no signal on one chance, same accuracy for good and bad results."""
    p_name, acc = diag["name"], constant(diag["acc"])
    if not (0.5 <= acc <= 1):
        return None
    cost_f = Formula("abs(" + str(diag.get("cost") or "0") + ")")
    base = scope(model, draws=draws)
    p = np.broadcast_to(np.asarray(base[p_name], float), (n,))
    cost = float(np.mean(np.broadcast_to(cost_f(base), (n,))))
    w_pos = p * acc + (1 - p) * (1 - acc)
    res, with_info = {}, 0.0
    for key, w, post in (("pos", w_pos, np.divide(p * acc, w_pos, out=np.zeros(n), where=w_pos > 0)),
                         ("neg", 1 - w_pos, np.divide(p * (1 - acc), 1 - w_pos, out=np.zeros(n), where=(1 - w_pos) > 0))):
        live = w > 0
        v, _, _ = worlds(model, {**draws, p_name: post}, n)
        wsum = float(w[live].sum())
        evs = [float((w[live] * v[k][live]).sum() / wsum) if wsum > 0 else 0.0 for k in range(len(v))]
        best = int(np.argmax(evs))
        res[key] = {"P": wsum / n, "ev": evs, "bestIdx": best}
        with_info += wsum / n * evs[best]
    now = float(vals.mean(axis=1).max())
    res.update(now=now, nowIdx=int(np.argmax(vals.mean(axis=1))), cost=cost, evsi=max(0.0, with_info - now))
    res["enbs"] = res["evsi"] - cost
    res["changes"] = res["pos"]["bestIdx"] != res["neg"]["bestIdx"]
    p0 = scope(model)[p_name]
    wp = p0 * acc + (1 - p0) * (1 - acc)
    res.update(postPos=p0 * acc / wp, postNeg=p0 * (1 - acc) / (1 - wp), pGood=wp)
    res["pkWindows"] = pk_windows(model, p_name, acc, cost_f)
    return res


def pk_windows(model: Model, p_name: str, acc: float, cost_f: Formula):
    """Band of the chance in which buying the signal beats deciding now, everything else at likely values."""
    def gain(p):
        p = np.atleast_1d(np.asarray(p, float))
        env = scope(model, overrides={p_name: p})
        no_test = option_values(model, env, len(p))[0].max(axis=0)
        wp = p * acc + (1 - p) * (1 - acc)
        with_test = np.zeros(len(p))
        for w, post in ((wp, np.divide(p * acc, wp, out=np.zeros(len(p)), where=wp > 0)),
                        (1 - wp, np.divide(p * (1 - acc), 1 - wp, out=np.zeros(len(p)), where=(1 - wp) > 0))):
            best = option_values(model, scope(model, overrides={p_name: post}), len(p))[0].max(axis=0)
            with_test += np.where(w > 0, w * best, 0.0)
        with_test -= np.broadcast_to(cost_f(env), (len(p),))
        return with_test - no_test

    ps = np.linspace(0, 1, PK_POINTS)
    better = gain(ps) > 1e-9

    def edge(x0, x1, inside_at_x1):
        for _ in range(80):
            m = (x0 + x1) / 2
            if (gain(m)[0] > 1e-9) == inside_at_x1:
                x1 = m
            else:
                x0 = m
        return (x0 + x1) / 2

    out, i = [], 0
    while i < len(ps):
        if better[i]:
            j = i
            while j + 1 < len(ps) and better[j + 1]:
                j += 1
            lo = 0.0 if i == 0 else edge(ps[i - 1], ps[i], True)
            hi = 1.0 if j == len(ps) - 1 else edge(ps[j + 1], ps[j], True)
            out.append([lo, hi])
            i = j + 1
        else:
            i += 1
    return out


# ---------------------------------------------------------------------------------------------------------------
def run_case(case: dict) -> dict:
    state = case["state"]
    model = build_model(state)
    seed = str(state.get("seed", 2364))
    point, bad_point, env0 = point_values(model)
    out = {
        "options": model.labels,
        "point": [float(x) for x in point],
        "pointLeader": int(np.argmax(point)),
        "pointBad": bad_point,
        "scope": {k: float(np.asarray(v)) for k, v in env0.items()},
        "breakevens": {name: switch_points(model, name) for name in model.order},
        "isProb": {name: name in model.prob_names for name in model.order},
    }
    draws = crn_draws(model, seed)
    vals, bad, _ = worlds(model, draws, N_WORLDS)
    out["sim"], out["pair"] = summarize(vals, point)
    out["sim"].update(N=N_WORLDS, badWorlds=int(bad.sum()), hasRanges=bool(model.ranges))
    out["drawsHead"] = {k: [float(x) for x in v[:5]] for k, v in draws.items()}
    out["evppi"] = {k: evppi_regression(vals, draws[k]) for k in model.ranges}
    out["evppi_exact"] = {k: evppi_exact(model, draws, k, N_WORLDS) for k in model.ranges}
    ind_vals, ind_bad, _ = worlds(model, independent_draws(model), N_INDEPENDENT)
    ind = summarize(ind_vals, point)[0]
    out["independent"] = {"N": N_INDEPENDENT, "badWorlds": int(ind_bad.sum()), "opts": ind["opts"], "evpi": ind["evpi"]}
    out["ranges"] = {k: {"L": r.L, "U": r.U, "likely": r.m, "a": r.a, "b": r.b, "mean": r.mean} for k, r in model.ranges.items()}
    d = state.get("diag") or {}
    if d.get("on") and d.get("name"):
        out["diag"] = diagnostic(model, draws, vals, d, N_WORLDS)
    return out
