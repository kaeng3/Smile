from __future__ import annotations
import argparse
import logging
from datetime import date

from jusmo_scanner.config import load_config, load_telegram_credentials

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jusmo-scanner", description="jusmo-scanner CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan", help="Run the EOD scan")
    scan_p.add_argument("--provider", choices=["csv", "pykrx", "kis"], default="csv")
    scan_p.add_argument("--csv-dir", default="data")
    scan_p.add_argument("--cache-dir", default="data/cache/current-three-years", help="kis provider persistent raw cache directory")
    scan_p.add_argument("--start", type=date.fromisoformat, metavar="YYYY-MM-DD",
                        help="kis/pykrx fetch start; default: three calendar years before --end")
    scan_p.add_argument("--end", type=date.fromisoformat, metavar="YYYY-MM-DD",
                        help="kis/pykrx fetch end; default: today")
    scan_p.add_argument("--refresh", action="store_true", help="kis provider: ignore the cache and refetch")
    scan_p.add_argument("--db-path", default="data/scan.db")
    scan_p.add_argument("--config", default="config/scanner.yaml")
    scan_p.add_argument("--notify", action="store_true")

    validate_p = sub.add_parser("validate-config", help="Validate config/scanner.yaml and Telegram env vars")
    validate_p.add_argument("--config", default="config/scanner.yaml")

    tg_p = sub.add_parser("telegram-test", help="Check Telegram credentials, optionally send a real test message")
    tg_p.add_argument("--send", action="store_true", help="Actually send a message; default is a dry run that only validates credentials load")

    from jusmo_scanner.backtest import cli_commands
    cli_commands.add_parsers(sub)

    return parser


def _cmd_scan(args: argparse.Namespace) -> int:
    from jusmo_scanner.data.csv_provider import CSVProvider
    from jusmo_scanner.jobs import scan_eod
    from jusmo_scanner.notifier.telegram import TelegramNotifier

    cfg = load_config(args.config)
    if args.provider != "csv":
        end = args.end or date.today()
        if args.start is not None:
            start = args.start
        else:
            try:
                start = end.replace(year=end.year - 3)
            except ValueError:  # February 29 has no counterpart three years earlier.
                start = end.replace(year=end.year - 3, day=28)
        if start > end:
            logger.error("--start must be on or before --end")
            return 1
    if args.provider == "csv":
        provider = CSVProvider(args.csv_dir)
    elif args.provider == "kis":
        from jusmo_scanner.data.kis_provider import KisProvider
        try:
            provider = KisProvider(start_date=start.isoformat(), end_date=end.isoformat(),
                                   cache_dir=args.cache_dir, refresh=args.refresh)
        except ValueError as exc:
            logger.error("%s", exc)
            return 1
    else:
        from jusmo_scanner.data.pykrx_provider import PykrxProvider
        provider = PykrxProvider(start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))

    notifier = None
    if args.notify:
        token, chat_id = load_telegram_credentials()
        notifier = TelegramNotifier(bot_token=token, chat_id=chat_id)

    try:
        scan_eod.run(provider, cfg, args.db_path, notifier=notifier)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1
    finally:
        if hasattr(provider, "close"):
            provider.close()
    return 0


def _cmd_validate_config(args: argparse.Namespace) -> int:
    load_config(args.config)
    logger.info("config OK: %s", args.config)
    try:
        load_telegram_credentials()
        logger.info("Telegram credentials OK")
    except RuntimeError as exc:
        logger.warning("Telegram credentials not configured: %s", exc)
    return 0


def _cmd_telegram_test(args: argparse.Namespace) -> int:
    from jusmo_scanner.notifier.telegram import TelegramNotifier

    token, chat_id = load_telegram_credentials()
    if not args.send:
        logger.info("Dry run: Telegram credentials loaded OK (chat_id=%s). Pass --send to actually deliver a message.", chat_id)
        return 0
    notifier = TelegramNotifier(bot_token=token, chat_id=chat_id)
    notifier.send_message("jusmo-scanner 테스트 메시지입니다.")
    logger.info("test message sent")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        return _cmd_scan(args)
    if args.command == "validate-config":
        return _cmd_validate_config(args)
    if args.command == "telegram-test":
        return _cmd_telegram_test(args)
    if args.command in ("backtest", "backtest-report", "sample-data"):
        from jusmo_scanner.backtest import cli_commands
        return cli_commands.dispatch(args)
    parser.error(f"unknown command: {args.command}")
    return 2
