"""radar command-line interface (`run` is wired to radar.run)."""

import argparse
from pathlib import Path

from radar import __version__, config


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="radar", description="Private hackathon radar")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    subparsers = parser.add_subparsers(dest="command")
    run_parser = subparsers.add_parser(
        "run", help="fetch all sources, render tables, commit data"
    )
    run_parser.add_argument(
        "--sources",
        metavar="A,B",
        help="comma-separated source ids to run (default: all enabled sources)",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="skip git entirely (output files are still written)",
    )
    run_parser.add_argument(
        "--no-push", action="store_true", help="commit but do not push"
    )
    run_parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="max events to take per source (must be >= 1)",
    )
    run_parser.add_argument(
        "--data-dir",
        type=Path,
        metavar="PATH",
        help="output directory (default: repo data/; a custom dir requires --dry-run)",
    )
    return parser


def _print_run_summary(summary: dict, data_dir: Path) -> None:
    """Human run summary: counts, failed sources, output path."""
    print(
        f"new={summary['new']} updated={summary['updated']} "
        f"closed={summary['closed']} removed={summary['removed']} "
        f"total_open={summary['total_open']}"
    )
    if summary["failed"]:
        for failure in summary["failed"]:
            print(f"failed: {failure['source']}: {failure['error']}")
    else:
        print("failed: none")
    print(f"output: {data_dir}")


def main(argv=None) -> int:
    """Run the radar CLI; returns the process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(f"radar {__version__}")
        return 0

    if args.command == "run":
        sources = None
        if args.sources is not None:
            sources = [part.strip() for part in args.sources.split(",") if part.strip()]
            if not sources:
                parser.error("--sources needs at least one source id")
        if args.limit is not None and args.limit < 1:
            parser.error("--limit must be >= 1")
        from radar import run as runner  # local import keeps --version/--help cheap

        try:
            summary = runner.run(
                sources=sources,
                dry_run=args.dry_run,
                no_push=args.no_push,
                limit=args.limit,
                data_dir=args.data_dir,
            )
        except Exception as exc:  # hard error: report and exit non-zero
            print(f"radar run failed: {type(exc).__name__}: {exc}")
            return 1
        _print_run_summary(summary, args.data_dir or config.DATA_DIR)
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
