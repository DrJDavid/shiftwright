# WS4 request: call-ins and `preferred_off` (for WS1 `fix_day`, SEMANTICS)

From WS4 (scenarios), Fri Nov 6 ~23:30 CT.

The demo store keeps the two demo-phone employees (e023, e027) free on Saturday with a
`preferred_off` entry for Saturday (weight $60/h of overlap), so the weekly solve doesn't schedule
them and they can be called in at 06:04. The weight is high on purpose: it has to beat the gap
penalties of the roles they're trained for ($60–70/h).

**Ask:** in `fix_day`, a `call_in` should not be charged the employee's `preferred_off` /
`preferred_on` weights. A call-in is asked by text and needs the employee's consent, so their
preference is already respected when they say yes or no. If `fix_day` prices it, the demo phones
cost +$60/h, drop to the bottom of the outreach queue, and may lose to `drop_coverage`.

Ranking should then follow the brief: coverage gained per dollar × `est_accept_prob`
(`(accepted+1)/(offered+2)`). The demo phones have 9/10 and 8/9 (0.83, 0.82); nobody else in the
store is above 0.7.

**Decision (David, Sat Nov 7 00:30 CT): ACCEPTED as SEMANTICS.md #16.**
