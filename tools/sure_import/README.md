# Sure migration planner

`build_plan.py` reads Sure's `all.ndjson` from a family export ZIP and writes a
Firefly III API plan. It is intentionally read-only: it never contacts Firefly
and does not modify either application.

```powershell
python tools/sure_import/build_plan.py C:\path\to\sure_export.zip --output migration-plan.json
```

Review `manual_review` and the operation counts before any future apply step.
The current plan covers accounts, categories, tags, budgets, ordinary
transactions and paired transfers. It explicitly holds trades, holdings,
valuations, recurring transactions, rules, balance snapshots, rejected
transfers, non-standard liabilities and split transactions for review.

The target Firefly API must only be populated after a backup and an approved
test import. The operations use Firefly `external_id` plus duplicate checking
to support a controlled re-run; that is not a substitute for reconciliation.
