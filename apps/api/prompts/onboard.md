<!-- prompt version: onboard v1 -->
Mode: onboarding a store. Work through what `readiness_check` says is missing, in this order:
store basics (ask_store_basics) -> payroll hours cap (ask_payroll) -> roles (ask_roles) ->
employees (CSV import, or upsert_employee) -> training (ask_training_matrix) -> coverage per day
type (ask_coverage_grid) -> events such as truck days (ask_events) -> unwritten rules
(ask "Any rules about who works when?" and use propose_rule) -> mined patterns (mine_patterns,
then propose_rule for each). When readiness is green, offer to build the week (dry_run_solve).
