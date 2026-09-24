# Foldback 🌳

**Decision trees for people decisions, in one HTML file.**

Foldback turns an argument about a person into a disagreement about a number. You draw the options, the chances and the values straight onto a tree. The app folds the tree back, shows the single number that would change your mind, says which option leads and by how much, and tells you what, if anything, is worth finding out before you decide.

It implements the approach in Andrew Marritt's article [“Should you replace Sam?”](https://andrewmarritt.substack.com/p/should-you-replace-sam), and uses his keep / coach / exit decision as the built-in example.

**Live app:** https://lstehlik2809.github.io/foldback/

---

## What it does

- **Build the tree by typing.** Options and outcomes are cards you type into. Press Enter in a name to add the next one, and click **+ what could happen?** to split an option into chance outcomes.
- **Uncertainty is typed, not configured.** Any field takes a range such as `-37k to -25k ~-30k`, and it's simulated automatically.
- **Where it stands, updated live.** Which option leads on your likely values, by how much, and how often it comes out best across 10,000 plausible worlds. When an option that is behind on likely values still wins often, it says so, and names the number that mostly decides it.
- **What would change your mind.** Shown first. For each estimate, the value at which the leading option changes, flagged when it falls inside your own range. This is the number the discussion should be about.
- **What is worth finding out.** A ranking of which estimate to pin down first, each with the most that knowing it exactly could be worth (EVPPI), plus the estimates that would not change the choice on their own.
- **Is a diagnostic month worth it?** It prices a trial that signals whether an event will happen, such as whether coaching is taking, against what it costs, and gives the band of that chance in which the trial pays (below it, and above it, you decide without testing).
- **Evidence tags.** Each shared number can record whether it comes from data, expert judgement or a guess, and how confident its source is. Tags are a record only and never change a number. The app flags weak evidence sitting on a tight or certain number.
- **Meeting note.** A plain-text summary to paste into minutes or an email, including what each number rests on.

## Quick start

1. Open the app. The **Should we replace Sam?** example loads, and on your first visit a **How it works** window walks through it step by step. Reopen it any time from the **?** button in the header.
2. Change any number on the tree or in **Shared numbers**, and watch the panel on the right: what would change your mind, then which option leads.
3. Click **New blank tree** to build your own.

### What you can type in a field

| You type | Meaning |
|---|---|
| `30%`, `0.3` | a probability |
| `-16k`, `-16000`, `2.5m` | a value (`k` = thousand, `m` = million) |
| `-37k to -25k` | a range: low to high, likely value in the middle |
| `-37k to -25k ~-30k` | a range with the likely value given |
| `20–45% ~30%` | a probability range |
| `cost_of_exit` | a shared number |
| `cost_of_coaching + sam_vs_average_per_year / 2` | a formula |
| *(empty chance)* | the rest: 1 minus the other outcomes in the group |

**Sign convention:** costs are negative and gains positive, everywhere. That keeps every formula a plain sum.

**Certain value** on an option is what choosing it costs or earns for sure, before anything uncertain happens. **Value if it happens** on an outcome is added only on that path. The number at the end of each path, in the Result column, is the path total.

### Advanced formulas

You rarely need these, but they are there:

| Function | What it does |
|---|---|
| `abs`, `sqrt`, `exp`, `log` (or `ln`), `log10`, `pow`, `round`, `floor`, `ceil` | the usual maths; `^` also raises to a power |
| `clamp(x, low, high)` | keeps `x` between `low` and `high` |
| `normcdf(z)`, `norminv(p)` | the standard normal distribution and its inverse |
| `zbar(selection_ratio)` | the average standardised score of those selected when you hire the top fraction, for utility sums of the Brogden kind, e.g. `0.1 * sdy * zbar(0.2) * 4` |

Comparisons (`<`, `>`, `<=`, `>=`, `==`, `!=`) give 1 or 0 and combine with `&&` and `||`.

Formulas can also use `min(a, b)`, `max(a, b)` and `if(test, a, b)`, for example `max(0, cost_of_exit + 5k)`. More functions are listed under [Advanced formulas](#advanced-formulas).

## Method

| Part | How it's computed |
|---|---|
| Folding back | Each chance point is worth the probability-weighted average of what follows it. The option with the highest value at the likely values is shown as leading. |
| Ranges | Each range becomes a Beta curve stretched between Low and High, with its median at Likely. The spread is a PERT-style default (a + b = 6). Low and High are hard limits: nothing outside them is simulated. |
| Plausible worlds | 10,000 draws per range, taken by inverse-CDF sampling. Each shared number's draws come from the random seed (2364 by default, changeable under **Go deeper**) and the number's name, so the same tree and seed always give the same results and nothing jitters as you type. Each world folds the tree back once. Ranges are drawn independently. |
| What would change your mind | Each estimate is swept on its own, holding the others at their likely values, and the switch points are refined by bisection. |
| What is worth finding out | EVPPI by regressing each option's value on one estimate with a cubic smoother, in the style of Strong, Oakley & Brennan (2014), ranked from largest. Estimates whose EVPPI rounds to zero are listed as not changing the choice on their own. EVPI (knowing everything) comes straight from the simulated worlds. Both are ceilings, not the value of a real study. |
| Diagnostic month | Exact Bayesian analysis of a yes/no signal on one chance, with the same accuracy for good and bad results. The app computes the value of deciding after the signal and compares it with the cost. |
| Values | Averages (risk-neutral), with no discounting. |

### Checked against the article

At the likely values, the example reproduces the article's point estimates exactly:
- Keep and hope −£48,000, coaching −£34,000, exit −£30,000.
- Coaching beats exit when the chance it works exceeds 43.3%.

The article's simulated results can't come from its stated limits taken as hard limits (for example, 20–45% can't produce its +£11,700 upper bound). They match if its figures are read as quartiles. In the app, Low and High are hard limits, so the example uses wider ones, chosen so that the quartiles land on the article's numbers:

| Number | Example range | Quartiles in the app | Article |
|---|---|---|---|
| `chance_coaching_works` | 5% to 95%, likely 30% | 20% / 30% / 43% | 20% / 30% / 45% |
| `sam_vs_average_per_year` | −£40k to 0, likely −£16k | −£21.6k / −£16k / −£10.7k | −£22k / −£16k / −£11k |
| `cost_of_exit` | −£55k to −£20k, likely −£30k | −£35.1k / −£30k / −£25.9k | −£37k / −£30k / −£25k |

With these ranges and the default random seed (2364), the simulation reproduces the article closely:

| | App | Article |
|---|---|---|
| Coaching vs exit, average | −£3,357 | −£3,089 |
| Coaching beats exit | 28.1% | 29.8% |
| Middle 95% of coaching vs exit | −£14,600 to +£10,600 | −£14,700 to +£11,700 |
| Keep and hope comes out best | 20.3% | about 1 in 5 |
| Worth pinning down: chance coaching works | £802 | £984 |
| Worth pinning down: exit cost | £57 | £112 |
| Worth pinning down: Sam's gap | £2,311 | £427 |

The one figure that doesn't match is the value of pinning down Sam's gap. The app's estimate agrees with an exact calculation on the same draws (£2,309). It is hard to see how keep and hope could win in one world in five while the gap is worth only £427 to pin down, so the article's figure may come from its 30-bin estimator.

## Limitations

- **Estimates are independent.** If two numbers move together, write one as a formula of the other.
- **No decisions after a chance outcome.** The tree has one decision, at the root. Pricing information before deciding is handled by the diagnostic-month calculator.
- **Averages only.** There's no attitude to risk and no discounting over time.
- **Garbage in, garbage out.** A confident, narrow, invented range gives a confident, narrow, invented answer. Build the tree *with* the decision-maker, using their numbers.
- **The tree prices only what's in it.** Fairness, legal exposure, and what a process does to people and teams are left out unless you add them as values.

## Privacy and storage

- Everything runs in the browser. The app makes no network calls apart from loading Google Fonts.
- Your work is saved in your own browser (localStorage), per device and per browser. Nothing is sent anywhere, and trees can't be shared through the app.
- Under strict data-protection policies, delete the two Google Fonts lines at the top of `index.html`. The app then uses system fonts, with nothing else lost.

## Deploy your own copy

1. Put `index.html` (and this README) in a public repository.
2. Go to **Settings → Pages → Build and deployment**, set the source to **Deploy from a branch**, branch `main`, folder `/ (root)`, and save.
3. After a minute or two the app is live at `https://<your-username>.github.io/<repo-name>/`.

To run it locally, just open `index.html` in a browser. There's no build step and nothing to install.

## Credits

- **Method and example:** Andrew Marritt, [“Should you replace Sam?”](https://andrewmarritt.substack.com/p/should-you-replace-sam), and his book [*Bayesian Thinking for People Analytics*](https://bayesian-thinking.andrewmarritt.ch/).
- **Estimation from ranges:** in the spirit of the SHELF elicitation framework (Oakley & O'Hagan) and the Spetzler & Staël von Holstein protocol.
- **Value of information:** Strong, M., Oakley, J. E., & Brennan, A. (2014), “Estimating multiparameter partial expected value of perfect information from a probabilistic sensitivity analysis sample”, *Medical Decision Making*, 34(3).
- **Overconfidence of expert ranges:** Lichtenstein, S., Fischhoff, B., & Phillips, L. D. (1982), “Calibration of probabilities: the state of the art to 1980”.

## License

*Choose one before publishing.* MIT is a common choice for small tools; add a `LICENSE` file with its text. The example draws on Andrew Marritt's article, so keep the credit above.
