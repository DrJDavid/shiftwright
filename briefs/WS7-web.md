# WS7 — Web app

**Folder:** `apps/web/` · **Oversight:** David
**Read first:** `SPEC.md`, `contracts/API.md`, generated `src/contracts.ts`

## Goal
The surface the judges see. Clear, fast, credible on a projector. A tool for a store leader,
not a toy.

## Layout
Three panes: **Chat** (left, ~35%) · **Main** (center: tabs Schedule / Coverage / Fix) ·
**Rulebook** (right, collapsible).

1. **Chat.** Streams SSE text; renders cards inline (one React component per `card_type`, in
   `src/cards/`). A card locks after submit and shows a compact summary. File drop on the chat
   opens a `csv_import` card. A small activity line shows `tool` events.
2. **Rulebook.** Grouped: Law · Corporate · Store rules · Employee preferences · Not modeled.
   Each line: plain-language note, hard/soft badge, $ weight, source chip, status (provisional
   rules shown dimmed with Confirm/Reject). Law lines expand to show the citation link and date.
   Top: **readiness meter** (checklist from `/readiness`) and **Build schedule** button.
3. **Schedule tab.** Employee × day grid; shift bars colored by role segments; breaks shown as
   gaps; hover for details. Header stats: hours used / cap (bar), cost, coverage %, gap
   penalty, validator badge ("0 hard violations ✓", clickable for the report).
4. **Coverage tab.** Heatmap: role × time slot for the selected day, required vs covered; gaps
   red. Click a gap → side sheet with the plain-language explanation + per-employee reasons.
5. **Fix tab.** "Report call-outs" (pick employees, time) → plan view: before/after coverage,
   immediate actions list, outreach queue. **Start texting** → live SMS thread (phone-style
   bubbles) driven by `/outreach`; in mock mode each outbound bubble has Yes/No buttons for
   replying as the employee. Coverage number animates as accepts come in.

## Quality bar
- Times shown as 12-hour local ("6:30a"); money as $1,234; never raw minute ints.
- Works at 1280×720 (projector). Loading and error states everywhere; the solve button shows progress.
- Generated types only; no `any` on API data.
- Make a deliberate visual design choice (frontend-design guidance if available): calm,
  professional, high-contrast. Not a default template look.

## Milestones
M1: schedule grid from `/solve` on the demo store + chat with `store_basics` and `payroll` cards.
M2: all cards, rulebook, readiness, coverage heatmap, gap explanations.
M3: Fix tab with outreach.

## Acceptance
A first-time user can go from an empty store to a solved week using only the demo CSVs and the
chat, without touching dev tools.
