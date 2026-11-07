# WS1 request: let breaks (and the segments around them) sit off the slot grid

**What.** Relax "Every start/end must be a multiple of Store.slot_minutes" for `Break.start/end`
and the `RoleSegment` boundaries adjacent to a break (e.g. allow 5-minute granularity there).
`Shift.start/end` stay on the grid.

**Why.** Law packs have short breaks (CA rest break: 10 min, paid). On a 30-min grid the engine must
round each one up to 30 min. That costs paid hours and coverage, and makes some real stores look
infeasible: on tiny_store under CA, two leaders can't keep `leader_on_duty` always staffed because
each 8 h shift carries 2×30 min rest + 30 min meal that the other leader must cover.

**Fields.** `Break.start`, `Break.end`, `RoleSegment.start`, `RoleSegment.end` (docstring change only;
no schema change). Validator would measure coverage per minute, or treat a slot as covered if
covered for at least N minutes.

**Until then.** Engine rounds break durations up to the slot size (documented in packages/engine/STATUS.md).


---
**Decision (David, Fri Nov 6 22:30 CT): ACCEPTED in contracts v1.1.** See `contracts/SEMANTICS.md`.
