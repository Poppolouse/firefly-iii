# Sure migration planner

`build_plan.py` reads Sure's `all.ndjson` from a family export ZIP and writes a
Firefly III API plan. It is intentionally read-only: it never contacts Firefly
and does not modify either application.

```powershell
python tools/sure_import/build_plan.py C:\path\to\sure_export.zip --output migration-plan.json
```

Review `manual_review` and the operation counts before any future apply step.
The current plan covers accounts, categories, tags, ordinary transactions and
paired transfers. It explicitly holds Sure's dated budget allocations, trades,
holdings, valuations, recurring transactions, rules, balance snapshots,
rejected transfers, non-standard liabilities and split transactions for review.

The target Firefly API must only be populated after a backup and an approved
test import. The operations use Firefly `external_id` plus duplicate checking
to support a controlled re-run; that is not a substitute for reconciliation.

After creating a disposable Firefly test user plus a personal access token, the
plan can be checked without writes:

```powershell
python tools/sure_import/apply_plan.py migration-plan.json
```

Only an explicit `--apply` sends requests to Firefly. Keep the token out of
files and command history by setting `FIREFLY_ACCESS_TOKEN` in the shell for
that one command. Alternatively, create the ignored local file
`infra/local/firefly-access-token.env` containing
`FIREFLY_ACCESS_TOKEN=...` and pass it with `--token-file`. The applier stops
at the first failed write and only skips pre-existing accounts, categories,
tags and budgets by name. A plan with review items requires the additional,
explicit `--allow-manual-review` flag; it imports only its automatic operations
and leaves every review item untouched.
