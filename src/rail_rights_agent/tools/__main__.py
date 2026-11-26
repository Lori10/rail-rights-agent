"""Command line: ``python -m rail_rights_agent.tools {seed,delay,compensate}``.

``seed`` and ``delay`` are live (configured profile, deployed tools stack); ``compensate`` is
offline and makes no AWS call.
"""

import argparse
import json
import sys
from collections.abc import Sequence

from botocore.exceptions import BotoCoreError, ClientError

from rail_rights_agent.aws import StackError, session, stack_outputs
from rail_rights_agent.settings import load_settings
from rail_rights_agent.tools import compensation as rules
from rail_rights_agent.tools.delays import TripStore, parse_travel_date
from rail_rights_agent.tools.deployment import OUTPUT_TRIPS_TABLE, STACK_NAME
from rail_rights_agent.tools.errors import ToolError
from rail_rights_agent.tools.handlers import compensation_json, compensation_request, trip_json
from rail_rights_agent.tools.seed_data import SEED_TRIPS


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m rail_rights_agent.tools",
        description="Seed and probe the agent's tools.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed", help="write the mock trips to the deployed trips table")
    delay = commands.add_parser("delay", help="look up a seeded trip's delay")
    delay.add_argument("train_number", help='e.g. "ICE 123"')
    delay.add_argument("travel_date", help="YYYY-MM-DD")
    comp = commands.add_parser("compensate", help="compute compensation offline")
    comp.add_argument("--price", required=True, help="ticket price in EUR, e.g. 29.90")
    comp.add_argument("--delay", required=True, type=int, help="arrival delay in minutes")
    comp.add_argument(
        "--kind", default=rules.TicketKind.SINGLE.value, choices=[k.value for k in rules.TicketKind]
    )
    comp.add_argument("--travel-class", default=2, type=int, choices=[1, 2])
    comp.add_argument(
        "--cause",
        default=rules.DelayCause.UNKNOWN.value,
        choices=[c.value for c in rules.DelayCause],
    )
    comp.add_argument("--informed-before-purchase", action="store_true")
    comp.add_argument("--reimbursed", action="store_true", help="already reimbursed under Art. 18")
    return parser


def _trips_table() -> tuple[TripStore, str]:
    aws = session(load_settings())
    table = stack_outputs(aws.client("cloudformation"), STACK_NAME, [OUTPUT_TRIPS_TABLE])
    name = table[OUTPUT_TRIPS_TABLE]
    return TripStore(aws.client("dynamodb"), name), name


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "compensate":
            request = compensation_request(
                {
                    "ticket_price_eur": args.price,
                    "delay_minutes": args.delay,
                    "ticket_kind": args.kind,
                    "travel_class": args.travel_class,
                    "cause": args.cause,
                    "informed_before_purchase": args.informed_before_purchase,
                    "reimbursed_under_art_18": args.reimbursed,
                }
            )
            print(json.dumps(compensation_json(rules.calculate_compensation(request)), indent=2))
        elif args.command == "seed":
            store, name = _trips_table()
            print(f"Wrote {store.put_many(SEED_TRIPS)} trips to {name}")
        else:
            day = parse_travel_date(args.travel_date)
            store, _ = _trips_table()
            print(json.dumps(trip_json(store.get(args.train_number, day)), indent=2))
    except (ToolError, StackError, ClientError, BotoCoreError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
