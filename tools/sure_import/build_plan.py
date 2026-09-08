#!/usr/bin/env python3
"""Build a reviewable, non-mutating Firefly III API plan from a Sure export ZIP.

The script deliberately never contacts Firefly III. Review `migration-plan.json`
and its `manual_review` list before using a separate, explicitly authorised
apply step.
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path


ACCOUNT_TYPES = {
    "Depository": {"type": "asset", "account_role": "defaultAsset"},
    "Investment": {"type": "asset", "account_role": "defaultAsset"},
    "Crypto": {"type": "asset", "account_role": "defaultAsset"},
    "Property": {"type": "asset", "account_role": "defaultAsset"},
    "Vehicle": {"type": "asset", "account_role": "defaultAsset"},
    "OtherAsset": {"type": "asset", "account_role": "defaultAsset"},
    # Firefly's API only accepts defaultAsset or cashWallet for asset accounts.
    # Keep credit cards as asset accounts so their imported transactions remain
    # usable, and preserve the source account name instead of inventing a type.
    "CreditCard": {"type": "asset", "account_role": "defaultAsset"},
    "Loan": {"type": "liability", "liability_type": "loan", "liability_direction": "credit"},
    "OtherLiability": {"type": "liability", "liability_type": "debt", "liability_direction": "credit"},
}


def read_export(path: Path) -> list[dict]:
    with zipfile.ZipFile(path) as archive:
        if "all.ndjson" not in archive.namelist():
            raise ValueError("Sure export ZIP does not contain all.ndjson")
        return [json.loads(line) for line in archive.read("all.ndjson").decode("utf-8").splitlines() if line.strip()]


def value(data: dict, key: str, default=None):
    result = data.get(key, default)
    return result if result not in (None, "") else default


def api_operation(endpoint: str, payload: dict, source_id: str) -> dict:
    return {"method": "POST", "endpoint": endpoint, "source_id": source_id, "payload": payload}


def build_plan(records: list[dict]) -> dict:
    by_type: dict[str, list[dict]] = {}
    for record in records:
        by_type.setdefault(record["type"], []).append(record["data"])

    accounts = {item["id"]: item for item in by_type.get("Account", [])}
    categories = {item["id"]: item["name"] for item in by_type.get("Category", [])}
    merchants = {item["id"]: item["name"] for item in by_type.get("Merchant", [])}
    tags = {item["id"]: item["name"] for item in by_type.get("Tag", [])}
    transactions = {item["id"]: item for item in by_type.get("Transaction", [])}
    transfer_transaction_ids = set()
    operations: list[dict] = []
    review: list[dict] = []

    for account in accounts.values():
        accountable_type = value(account, "accountable_type")
        mapping = ACCOUNT_TYPES.get(accountable_type)
        if mapping is None:
            review.append({
                "kind": "account",
                "source_id": account["id"],
                "reason": f"Sure account type {accountable_type!r} needs a Firefly liability mapping review.",
            })
            continue
        payload = {
            "name": account["name"],
            "type": mapping["type"],
            "currency_code": value(account, "currency"),
        }
        if mapping["type"] == "asset":
            payload["account_role"] = mapping["account_role"]
        else:
            payload["liability_type"] = mapping["liability_type"]
            payload["liability_direction"] = mapping["liability_direction"]
            payload["notes"] = value(account, "notes")
        operations.append(api_operation("/api/v1/accounts", payload, account["id"]))

    for category in by_type.get("Category", []):
        operations.append(api_operation("/api/v1/categories", {"name": category["name"]}, category["id"]))
    for tag in by_type.get("Tag", []):
        operations.append(api_operation("/api/v1/tags", {"tag": tag["name"]}, tag["id"]))
    for transfer in by_type.get("Transfer", []):
        outgoing = transactions.get(transfer.get("outflow_transaction_id"))
        incoming = transactions.get(transfer.get("inflow_transaction_id"))
        transfer_transaction_ids.update(filter(None, [transfer.get("outflow_transaction_id"), transfer.get("inflow_transaction_id")]))
        if not outgoing or not incoming:
            review.append({"kind": "transfer", "source_id": transfer["id"], "reason": "One or both linked transactions are missing."})
            continue
        source = accounts.get(outgoing.get("account_id"))
        destination = accounts.get(incoming.get("account_id"))
        if not source or not destination:
            review.append({"kind": "transfer", "source_id": transfer["id"], "reason": "The source or destination account is unavailable."})
            continue
        amount = abs(float(value(outgoing, "amount", 0)))
        if amount == 0:
            review.append({"kind": "transfer", "source_id": transfer["id"], "reason": "The transfer amount is zero."})
            continue
        operations.append(api_operation("/api/v1/transactions", {
            "error_if_duplicate_hash": True,
            "apply_rules": False,
            "transactions": [{
                "type": "transfer", "date": outgoing["date"], "amount": f"{amount:.2f}",
                "currency_code": value(outgoing, "currency"), "description": value(outgoing, "name", "Sure transfer"),
                "notes": value(outgoing, "notes"), "source_name": source["name"], "destination_name": destination["name"],
                "external_id": transfer["id"],
            }],
        }, transfer["id"]))

    for transaction in transactions.values():
        if transaction["id"] in transfer_transaction_ids:
            continue
        account = accounts.get(transaction.get("account_id"))
        amount = float(value(transaction, "amount", 0))
        if account is None or amount == 0:
            review.append({"kind": "transaction", "source_id": transaction["id"], "reason": "Missing account or zero amount."})
            continue
        merchant = merchants.get(transaction.get("merchant_id"))
        payload = {
            "type": "withdrawal" if amount < 0 else "deposit", "date": transaction["date"],
            "amount": f"{abs(amount):.2f}", "currency_code": value(transaction, "currency"),
            "description": value(transaction, "name", "Sure transaction"), "notes": value(transaction, "notes"),
            "category_name": categories.get(transaction.get("category_id")),
            "tags": [tags[tag_id] for tag_id in transaction.get("tag_ids", []) if tag_id in tags],
            "external_id": transaction["id"],
        }
        if amount < 0:
            payload.update({"source_name": account["name"], "destination_name": merchant or "Sure imported expense"})
        else:
            payload.update({"source_name": merchant or "Sure imported income", "destination_name": account["name"]})
        operations.append(api_operation("/api/v1/transactions", {
            "error_if_duplicate_hash": True,
            "apply_rules": False,
            "transactions": [payload],
        }, transaction["id"]))
        if transaction.get("split_lines"):
            review.append({"kind": "transaction", "source_id": transaction["id"], "reason": "Split lines require a grouped Firefly transaction review."})

    # Sure budgets are dated allocation records linked through BudgetCategory,
    # not named budget definitions. Creating Firefly budgets from them would
    # silently invent a budgeting structure, so retain them for review.
    for unsupported in ("Trade", "Holding", "Valuation", "RecurringTransaction", "Rule", "RejectedTransfer", "Balance", "Budget", "BudgetCategory"):
        for item in by_type.get(unsupported, []):
            review.append({"kind": unsupported, "source_id": item["id"], "reason": "No automatic lossless Firefly mapping is implemented."})

    return {
        "format": "sure-to-firefly-api-plan/v1",
        "source_record_counts": dict(sorted((key, len(items)) for key, items in by_type.items())),
        "operations": operations,
        "manual_review": review,
        "summary": {"operation_count": len(operations), "manual_review_count": len(review)},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_zip", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = build_plan(read_export(args.export_zip))
    args.output.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(plan["summary"]))


if __name__ == "__main__":
    main()
