"""Shift.why: short factual lines per shift, from config + the schedule only (contracts v1.2)."""
from __future__ import annotations

from shiftwright_contracts.models import AvailabilityKind, ConstraintKind, Shift, Strength

from .output import coverage_map, paid_minutes
from .prep import DAY, Prep, _avail_for_day

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def hm(m: int) -> str:
    m %= DAY
    h, mm = divmod(m, 60)
    suf = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}:{mm:02d} {suf}" if mm else f"{h12} {suf}"


def span(a: int, b: int) -> str:
    sa, sb = hm(a), hm(b)
    if sa[-2:] == sb[-2:]:
        sa = sa[:-3]
    return f"{sa}–{sb}"


def annotate(p: Prep, shifts: list[Shift], extra: dict[str, list[str]] | None = None) -> list[Shift]:
    """Returns the shifts with `why` filled. `extra[shift.id]` lines go first (e.g. fixer context)."""
    cov = coverage_map(p, shifts)
    names = {r.id: r.name for r in p.cfg.roles}
    always = {c.params.get("role_id"): c.id for c in p.constraints
              if c.kind == ConstraintKind.always_staffed and c.strength == Strength.hard}
    week_min: dict[str, int] = {}
    for s in shifts:
        week_min[s.employee_id] = week_min.get(s.employee_id, 0) + paid_minutes(s)
    out = []
    for s in shifts:
        lines = list((extra or {}).get(s.id, []))
        base = s.day * DAY
        by_role: dict[str, int] = {}
        for g in s.segments:
            by_role[g.role_id] = by_role.get(g.role_id, 0) + g.end - g.start
        main_segs = sorted(s.segments, key=lambda g: -(g.end - g.start))
        for g in main_segs[:2]:
            dem = max((p.demand.get((g.role_id, base + t), 0) for t in range(g.start - g.start % p.slot, g.end, p.slot)),
                      default=0)
            n = names.get(g.role_id, g.role_id)
            if g.role_id in always:
                lines.append(f"Keeps {n} staffed {DAYS[s.day]} {span(g.start, g.end)} ({always[g.role_id]})")
            elif dem > 0:
                alone = all(cov.get((g.role_id, base + t), 0) <= 1
                            for t in range(g.start - g.start % p.slot, g.end, p.slot))
                lines.append(f"{'Only ' + n + ' on shift' if alone and dem == 1 else 'Covers ' + n} "
                             f"{DAYS[s.day]} {span(g.start, g.end)} (needs {dem})")
            else:
                lines.append(f"Works {n} {DAYS[s.day]} {span(g.start, g.end)}")
        e = p.emps.get(s.employee_id)
        if e is not None:
            lines.append(f"{week_min.get(e.id, 0) / 60:g}/{e.max_hours_week:g} h this week")
            for a in _avail_for_day(p, e, s.day):
                ov = max(0, min(s.end, a.end) - max(s.start, a.start))
                if ov and a.kind == AvailabilityKind.preferred_off:
                    lines.append(f"Overlaps preferred-off time {span(a.start, a.end)} by {ov / 60:g} h")
                elif ov and a.kind == AvailabilityKind.preferred_on:
                    lines.append(f"Inside preferred hours {span(a.start, a.end)}")
            if e.age < 18:
                lines.append(f"Minor (age {e.age}): within minor hour limits")
        out.append(s.model_copy(update={"why": lines}))
    return out
