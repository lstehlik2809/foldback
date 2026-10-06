# Tests

Ten decision cases, each run through the real app and through an independent Python implementation of the method in Andrew Marritt's [“Should you replace Sam?”](https://andrewmarritt.substack.com/p/should-you-replace-sam), then compared. Run them after any change to `index.html`.

```sh
pip install -r tests/requirements.txt       # numpy, scipy
python3 tests/run_tests.py                  # all cases, about 10 seconds
python3 tests/run_tests.py 03 07            # only cases whose file name starts with 03 or 07
```

Node.js and Playwright's Chromium are needed for the app side (`NODE_PATH` is found with `npm root -g` if it isn't set). The run prints one line per case and every failure, writes `tests/output/report.md` with the full comparison, and exits with 1 if anything fails. `--app-json tests/output/app_results.json` reruns the comparison on saved app results without a browser.

## What runs where

| File | What it does |
|---|---|
| `cases/*.json` | The ten cases. `state` is the app's own saved-tree format; `hand_checks` are numbers derived by hand with the article's algebra; `documented` are figures the main README publishes; `article` are the article's own figures, shown for context. |
| `app_runner.js` | Opens `index.html` in headless Chromium, puts each case into sessionStorage (where the app keeps a tree) and reloads, so the app loads, computes and renders it the normal way. It reads the app's results at full precision through a one-line hook added to a temporary copy; the app itself is not changed. |
| `reference.py` | The independent implementation: fold-back, switch points, plausible worlds with exact inverse-Beta draws, best-in shares, head to head, EVPI, EVPPI (the app's regression estimator and a near-exact conditional-expectation one), and the diagnostic month with its Pauker–Kassirer band. |
| `run_tests.py` | Runs both, compares them with tolerances fixed at the top of the file, and writes the report. |

## The cases

| # | Case | Main things it pins down |
|---|---|---|
| 01 | Sam, the article's point-estimate tree | −48k / −34k / −30k, the 43.3% threshold, every switch point by hand |
| 02 | Sam with ranges and a diagnostic month (the built-in example) | the README's published results, posteriors after the month |
| 03 | Sam, the replacement is also a bet (job drag *e*) | nested chance nodes, the 27.5% threshold, Table 2's three regimes |
| 04 | Jordan: the fourth branch, fixing the job | four options, a three-way race, switch points outside the range |
| 05 | Is a structured interview worth it (Brogden) | `zbar()`, formula numbers, ~£9,000 per hire, £2,240 per interview, £67k ceiling |
| 06 | Chris: replace or retain with the tenure asymmetry (Boudreau & Berger) | naive vs corrected tenure giving opposite answers |
| 07 | Priya: a PIP as a purchase of information | a near tie, EVSI, the band 37.3%–55.0% where the month pays |
| 08 | Mei: what to do with a flight risk of 0.62 | a chance defined by a formula of two ranges |
| 09 | Alex: promote or hire, ranges typed on the tree | anonymous ranges, worlds whose chances don't fit (4.5%, in closed form) |
| 10 | Outsourcing payroll, a lopsided range | likely-value leader ≠ average leader, narrow bands, seed 7 |

## What is compared

| Section | Check | Tolerance |
|---|---|---|
| App | page runs without script errors, no input errors, the panel names the leader | exact |
| Fold-back | every option at the likely values, every number and formula | 1 in a million |
| Switch points | sweep range, number of switch points, where, between which options, inside the range or not | 1 in a million of the sweep |
| Worlds (same random numbers) | first draws, averages, 2.5%/97.5% points, best-in shares, EVPI, worlds whose chances don't fit, head to head | 0.02% (averages) and 0.1% (2.5%/97.5% points) of the widest spread; shares within 0.002 |
| Worlds (independent stream, 200,000 worlds) | averages, best-in shares, worlds that don't fit | 4 standard errors |
| Value of information | EVPPI against the same regression estimator | 1% |
| | EVPPI against the near-exact value, and which number ranks first | WARN beyond 10% (or 2% of EVPI) |
| Diagnostic month | EVSI, cost, net value, chances and choices after a good or bad month, posteriors | as above, posteriors 1e-9 |
| | the band where the month pays | inside the exact band, at most one 1/201 grid step narrower at each end |
| Hand-derived | every `hand_checks` entry, on the reference and on the app | per entry |

Both sides use the same random numbers on purpose (the app's stream is reproduced in Python), so they can be compared tightly. The transform from random numbers to values, and everything after it, is computed independently. The separate 200,000-world stream checks that the app's random numbers themselves are sound.

Two things follow the app's conventions rather than the method, so the comparison is like for like: how far each number is swept for switch points (0–100% for chances, the range plus 75% of its width on each side for ranges, 0 to 3× the value for fixed numbers), and that a world whose chances pass 100% is still counted, with the empty outcome getting nothing.

## Do the tests catch real mistakes?

Each of these deliberate breaks to a copy of the app made the suite fail:

| Break | Failed checks |
|---|---|
| Range spread a + b = 5 instead of 6 | 196 |
| Value of a chance node dropped | 246 |
| Signal accuracy misapplied in the diagnostic month | 14 |
| Random seed ignored | 11 |
| Linear instead of cubic EVPPI smoother | 6 |
| Empty chance not floored at zero | 5 |
| Switch-point sweep of 24 steps instead of 240 | 2 |

## Adding a case

Copy a case file, give it a new `id`, build the tree in `state` (the format the app saves; `id`s must be unique and fixed, because ranges typed on the tree draw their random numbers from them), and add `hand_checks`. Metric names: `point:<option>`, `leader`, `mean_leader`, `scope:<number>`, `switches:<number>`, `pbest:<option>`, `mean:<option>`, `evpi`, `bad_share`, `pair:pB|meanDiff|q025|q975|challenger`, `evppi:<number>`, `evppi_equals_evpi:<number>`, `diag:postPos|postNeg|pGood|cost|evsi|pos_best|neg_best`, `pk_window`. A range typed on the tree is named `u_<card id>_value` or `u_<card id>_prob`.

## Findings from the first run (October 2026)

- The app agrees with the independent implementation everywhere: 1,112 checks, 0 failures.
- Its regression EVPPI is within 7.1% of the near-exact value wherever that value is above 50 (largest: flight risk in case 08, 86 vs 93; largest in money: job drag in case 04, 3,885 vs 3,755). Below 50 the gaps are at most 3. The ranking of what to pin down first matches in every case where one number clearly leads. In case 04 the top two are within 1% of each other on the near-exact values, and the app's estimator swaps them (job drag first, Jordan's gap second).
- The article's Figure 3 value for Sam's gap (£427) disagrees with the near-exact value on the built-in ranges (£2,303). It is also hard to square with the article's own finding that keep-and-hope wins in one world in five, which needs the gap to matter. The app's £2,311 is right for its inputs.
- The article's “around 57%” threshold for acting on coaching is not computed by the app. On the built-in ranges, the regret ratio from the worlds (average loss when coaching was wrong ÷ the sum of both average losses) is 58.4%, so the article's figure is consistent.
- The article says both tenure corrections in the Boudreau–Berger condition “run against the replacement”. That holds only for an incumbent above average (case 06). For one below average, a longer remaining tenure makes replacing *more* attractive.
