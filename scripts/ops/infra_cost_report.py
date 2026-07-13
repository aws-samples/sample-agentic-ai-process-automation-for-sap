#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Infrastructure Cost Report

Queries AWS Cost Explorer using the project's cost-allocation tags to produce
a monthly cost breakdown by architecture component.

Prerequisites:
    - Cost allocation tags activated in AWS Billing console:
      'project', 'architecture-component', 'exception-type'
    - Tags take 24h to appear in Cost Explorer after activation

Usage:
    python scripts/ops/infra_cost_report.py --stack-name my-stack --region us-east-1
    python scripts/ops/infra_cost_report.py --stack-name my-stack --months 3
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone

import boto3


def _month_range(months_back: int) -> tuple[str, str]:
    """Return (start, end) date strings for Cost Explorer."""
    now = datetime.now(timezone.utc)
    end = now.replace(day=1).strftime("%Y-%m-%d")
    start_year = now.year
    start_month = now.month - months_back
    while start_month <= 0:
        start_month += 12
        start_year -= 1
    start = f"{start_year}-{start_month:02d}-01"
    return start, end


def get_cost_by_tag(ce, stack_name: str, tag_key: str, start: str, end: str) -> dict:
    """Query Cost Explorer grouped by a tag key, filtered to this project."""
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        Filter={"Tags": {"Key": "project", "Values": [stack_name]}},
        GroupBy=[{"Type": "TAG", "Key": tag_key}],
    )
    totals = defaultdict(float)
    monthly = defaultdict(lambda: defaultdict(float))
    for period in resp["ResultsByTime"]:
        month = period["TimePeriod"]["Start"][:7]
        for group in period["Groups"]:
            tag_val = group["Keys"][0].removeprefix(f"{tag_key}$")
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            totals[tag_val] += amount
            monthly[month][tag_val] += amount
    return {"totals": dict(totals), "monthly": {k: dict(v) for k, v in monthly.items()}}


def get_cost_by_service(ce, stack_name: str, start: str, end: str) -> dict:
    """Query Cost Explorer grouped by AWS service, filtered to this project."""
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        Filter={"Tags": {"Key": "project", "Values": [stack_name]}},
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )
    totals = defaultdict(float)
    for period in resp["ResultsByTime"]:
        for group in period["Groups"]:
            service = group["Keys"][0]
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            totals[service] += amount
    return dict(totals)


def main():
    parser = argparse.ArgumentParser(description="Infrastructure Cost Report")
    parser.add_argument("--stack-name", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--months", type=int, default=1, help="Months of history (default: 1)"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output JSON instead of table"
    )
    args = parser.parse_args()

    ce = boto3.client("ce", region_name="us-east-1")  # Cost Explorer is us-east-1 only
    start, end = _month_range(args.months)

    print(f"Infrastructure Cost Report: {args.stack_name}")
    print(f"Period: {start} to {end}")
    print("=" * 60)

    print("\nBy Architecture Component:")
    by_component = get_cost_by_tag(
        ce, args.stack_name, "architecture-component", start, end
    )
    total = sum(by_component["totals"].values())
    for component, cost in sorted(by_component["totals"].items(), key=lambda x: -x[1]):
        label = component or "(untagged)"
        pct = (cost / total * 100) if total > 0 else 0
        print(f"  {label:25s}  ${cost:>8.2f}  ({pct:5.1f}%)")
    print(f"  {'TOTAL':25s}  ${total:>8.2f}")

    print("\nBy AWS Service:")
    by_service = get_cost_by_service(ce, args.stack_name, start, end)
    for service, cost in sorted(by_service.items(), key=lambda x: -x[1]):
        if cost >= 0.01:
            print(f"  {service:40s}  ${cost:>8.2f}")

    if args.months > 1 and by_component["monthly"]:
        print("\nMonthly Trend:")
        for month in sorted(by_component["monthly"]):
            month_total = sum(by_component["monthly"][month].values())
            print(f"  {month}:  ${month_total:.2f}")

    if args.json:
        report = {
            "stack_name": args.stack_name,
            "period": {"start": start, "end": end},
            "by_component": by_component,
            "by_service": by_service,
            "total_usd": round(total, 2),
        }
        print(f"\n{json.dumps(report, indent=2)}")


if __name__ == "__main__":
    main()
