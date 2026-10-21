"""Командная строка для локальной демонстрации очереди.

    python -m jobq.cli demo --jobs 5 --fail-every 3
    python -m jobq.cli types
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from .clock import ManualClock
from .dashboard import render_report
from .models import Job
from .queue import JobQueue
from .registry import HandlerRegistry
from .worker import Worker

logger = logging.getLogger(__name__)


def build_demo_registry(fail_every: int) -> HandlerRegistry:
    registry = HandlerRegistry()

    @registry.handler("echo")
    def echo(job: Job) -> object:
        return job.payload.get("message")

    @registry.handler("flaky")
    def flaky(job: Job) -> object:
        number = int(job.payload.get("n", 0))
        if fail_every and number % fail_every == 0:
            raise RuntimeError(f"flaky job #{number} failed")
        return number

    return registry


def cmd_demo(args: argparse.Namespace) -> int:
    clock = ManualClock()
    queue = JobQueue(clock=clock)
    worker = Worker(queue, build_demo_registry(args.fail_every), name="demo")

    for number in range(1, args.jobs + 1):
        queue.enqueue("flaky", {"n": number}, delay=float(number))
    queue.enqueue("echo", {"message": "hello"})

    for _ in range(args.jobs + 1):
        worker.run_pending()
        clock.advance(1.0)

    print(render_report(queue))
    return 0


def cmd_types(args: argparse.Namespace) -> int:
    for job_type in build_demo_registry(args.fail_every).job_types():
        print(job_type)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobq", description="jobq demo utility")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--fail-every", type=int, default=3, help="make every N-th flaky job fail")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="run a small simulated workload")
    demo.add_argument("--jobs", type=int, default=5)
    demo.set_defaults(func=cmd_demo)

    types = sub.add_parser("types", help="list demo job types")
    types.set_defaults(func=cmd_types)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
