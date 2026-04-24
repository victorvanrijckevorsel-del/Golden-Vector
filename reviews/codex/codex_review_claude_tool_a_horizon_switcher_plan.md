# Codex Review — Claude Tool A Horizon Switcher Plan

## Grade

**READY WITH MINOR CHANGES**

The plan is directionally good and fits the current Tool A architecture. The switcher itself is a good idea, and the backend-heavy / zero-JS approach is the right default for this repo. The main issue is not correctness — it is **scope discipline**. The plan is slightly more ambitious than “simplest possible” because it adds URL-managed line hiding and a new workspace-only narrative engine. Those are both survivable, but neither is the simplest shape for v1.

## Tight punch list

1. **Defer the `hide=` line-toggle feature unless Emanuel explicitly wants it in v1.**  
   The horizon switcher does not need per-line hide/show URLs to be useful. Showing all three lines and making the active one thicker is the simpler design.

2. **Do not add a brand-new workspace-only narrative engine if you can reuse the existing Tool A explanation builders.**  
   Extract or adapt shared helpers in [golden_vector/model/explanations.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/explanations.py) instead of inventing a second explanation system in the workspace.

3. **Use one structural-history source-of-truth on the detail page.**  
   The plan should explicitly retire the old 12M-only chart load path and reuse the already-loaded structural metrics history, rather than keeping two parallel “history” concepts alive.

4. **Tighten the volatility rule.**  
   If the active window is not structurally eligible, show volatility as unavailable instead of rendering a low-observation number with only a sample-size label.

5. **Fix the wording around “renders exactly as today.”**  
   With a switcher and a three-line chart, the page will not be literally identical. The better claim is: default load preserves the same active window and the same canonical numbers.

## Answers to the 7 review questions

### 1. Is the design actually as simple as it can be?

**No, but it is close.**

The simple core is:
- `?window=6m|12m|3y`
- full page re-render
- scatter / up-down beta / window-specific cards / narratives follow the selected window
- rolling chart shows all three lines with the active one highlighted

That is already enough to deliver the feature.

What pushes the plan past “simplest possible” is:
- `hide=` URL state
- legend toggle URL generation
- hidden-line persistence in bookmarks

Those are nice-to-have refinements, not the core feature. If you want the simplest viable version, cut them from v1.

### 2. Does “most calculation in the back end” hold?

**Yes.**

The proposed shape stays backend-led:
- URL params select the state
- Python slices the weekly sample
- Python recomputes volatility
- Python renders the SVG
- Python renders the active metrics and narrative

There is no silent drift back to client-side logic here. So on that requirement, the plan is good.

### 3. Is the narrative regeneration helper a reasonable seam?

**Not in the form currently proposed.**

The goal is correct: the detail page needs active-window explanations, and the precomputed pipeline text is anchor-window text.

But the simplest maintainable seam is **not** a fresh workspace-specific `_describe_structural_metrics(...)`.

A better shape is:
- reuse the existing explanation builders in [golden_vector/model/explanations.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/model/explanations.py)
- or extract a small shared “window explanation” adapter that both the pipeline and workspace can call

Why:
- the current builders already encode the key semantics and thresholds
- duplicating them in the workspace creates avoidable drift
- shared narrative logic is actually simpler here than two near-identical systems

So my recommendation is: **shared helper, not workspace-only helper**.

### 4. Volatility recomputation: should 6M vol be suppressed entirely when observations are thin?

**Yes — if the active window is not eligible, suppress it.**

A sample-size label is helpful, but it is not enough on its own.

Reason:
- the structural page is an official Tool A page, not a loose sandbox
- if a window is too thin to support the official structural read, showing window-specific volatility anyway can imply a level of trust the page is otherwise refusing to grant

The simplest trustworthy rule is:
- if active window status is `ELIGIBLE`, compute and show window-specific volatility
- otherwise show “not enough clean weekly observations for this window”

That is cleaner than inventing a separate volatility-specific threshold policy.

### 5. Chart line colors: any accessibility concern?

**Yes, but manageable.**

Use a colorblind-safe palette and one non-color cue:
- `6M`: blue
- `12M`: orange
- `3Y`: green or charcoal
- active line: thicker stroke
- optionally, inactive lines lighter opacity

Because you are staying zero-JS and SVG-only, I would avoid patterns or dash styles unless they are clearly needed. Stroke width + distinct colors is enough for v1.

### 6. URL param ergonomics: is there a cleaner abstraction than manual `hide` URL juggling?

**Yes: remove `hide` from v1.**

If you keep it, then yes, you should build one small helper that:
- parses current query params
- replaces `window`
- updates the hidden set
- preserves other params

But my honest answer is that the cleanest abstraction is: **do not need it yet**.

The horizon switcher is useful without hide toggles.

### 7. Does anything in this plan break the “prefer simpler designs first” rule?

**A little bit, yes.**

Not badly. But the following parts are more elaborate than they need to be for the first version:
- line-hide state in the URL
- legend toggle links
- a new workspace-specific narrative templating layer

The switcher itself does **not** violate the rule.  
The extra chart interactivity and duplicated explanation logic are the parts that do.

## Extra observations

### What the plan gets right

- The basic product idea is strong. A window switcher belongs on the Tool A detail page.
- The URL-param approach is correct for this app.
- Recomputing a small amount of window-specific math in Python is fine here.
- Keeping aggregate metrics visible but labeled as aggregate is the right call.

### One subtle current-code fact the plan should acknowledge

Today, the rolling-delta chart is actually a **12M chart**, not a fully anchor-driven chart:
- [_render_beta_history_panel](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:3295)
- [_safe_load_structural_history](C:/Users/Emanuel/code/Golden-Vector/golden_vector/serve/workspace.py:628)

So when the plan says “the page today is locked to the canonical anchor window,” that is only mostly true. In live latest output that is harmless because the current anchor is effectively `12M` everywhere, but the plan should still describe the current state accurately before changing it.

### My recommended v1 scope

If you want the cleanest implementation:

1. add `window=` URL param
2. render a 3-tab switcher
3. make scatter / up-down beta / window-specific cards follow the active window
4. show all three rolling lines at once
5. highlight the active line
6. keep aggregate metrics constant and label them
7. reuse shared explanation builders

Then, only if Emanuel later asks for more chart control:
- add `hide=` toggles as a second pass

## Bottom line

This is a **good plan**, but not yet the **simplest plan**.

If you cut the line-hide URL state and avoid a second explanation engine, I would call it clean and ready to implement immediately.
