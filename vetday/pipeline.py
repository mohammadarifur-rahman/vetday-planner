"""CLI: `python -m vetday.pipeline refresh [--no-llm] [--offline]` and `status`."""

import argparse
import logging
import sys
import time
from collections import Counter

from vetday import db
from vetday.config import OLLAMA_HOST, OLLAMA_MODEL
from vetday.extract import build_offer, llm_extract, make_structured_llm, ollama_status
from vetday.merge import merge_offers
from vetday.models import Offer, RawOffer
from vetday.overrides import load_overrides
from vetday.sources import SOURCES
from vetday.sources.base import FetchBlocked

log = logging.getLogger("vetday")


def collect_raw(conn, refresh_id: int, offline: bool) -> list[RawOffer]:
    raws: list[RawOffer] = []
    for src in SOURCES:
        try:
            html, fresh = src.fetch(offline=offline)
        except FetchBlocked as exc:
            print(f"  ! {src.NAME}: {exc}")
            db.record_source_run(conn, refresh_id, src.NAME, "blocked", 0, str(exc))
            continue
        parsed = src.parse(html)
        status = "ok" if fresh else "cached"
        if not parsed:
            status = "empty"
            print(f"  ! {src.NAME}: parser found 0 offers; the page layout may have changed")
        db.record_source_run(conn, refresh_id, src.NAME, status, len(parsed))
        print(f"  {src.NAME:<13} {status:<7} {len(parsed):>3} raw offers")
        raws.extend(parsed)
    return raws


def extract_all(conn, raws: list[RawOffer], use_llm: bool, model: str) -> list[Offer]:
    ov = load_overrides()
    llm = make_structured_llm(model) if use_llm else None
    offers: list[Offer] = []
    statuses: Counter[str] = Counter()
    started = time.monotonic()
    width = len(str(len(raws)))
    for i, raw in enumerate(raws, 1):
        t0 = time.monotonic()
        extraction, status = llm_extract(raw, llm, conn, model) if llm else (None, "rules")
        failed = status in ("fallback", "timeout")
        statuses[status] += 1
        offer = build_offer(raw, ov, extraction, llm_failed=failed)
        if offer.brand_key not in ov.exclusions:
            offers.append(offer)
        if llm:
            print(
                f"  [{i:>{width}}/{len(raws)}] {raw.brand[:40]:<40} ... "
                f"{time.monotonic() - t0:5.1f}s ({status})",
                flush=True,
            )
    if llm:
        total = time.monotonic() - started
        print(f"  LLM done in {total:.0f}s: " + ", ".join(f"{k} {v}" for k, v in statuses.items()))
    if statuses["fallback"] + statuses["timeout"]:
        n = statuses["fallback"] + statuses["timeout"]
        print(f"  ! {n} paragraphs fell back to rules-only (needs_verification=true)")
    return offers


def refresh(use_llm: bool, offline: bool, limit: int | None = None) -> int:
    model = OLLAMA_MODEL
    if use_llm:
        ok, msg = ollama_status(OLLAMA_HOST, model)
        print(msg)
        if not ok:
            print("Continuing rules-only. Re-run refresh after fixing Ollama for LLM summaries.")
            use_llm = False
    conn = db.connect()
    refresh_id = db.start_refresh(conn, "llm" if use_llm else "rules", model if use_llm else None)
    print("Fetching sources (one request each):")
    raws = collect_raw(conn, refresh_id, offline)
    if not raws:
        print("No offers parsed from any source; keeping the previous data.")
        return 1
    if limit:
        raws = raws[:limit]
        print(f"--limit {limit}: extracting only the first {limit} paragraphs (DB not replaced)")
    print(f"Extracting {len(raws)} offers ({'LLM + rules' if use_llm else 'rules only'})...")
    offers = extract_all(conn, raws, use_llm, model)
    names = {s.DISPLAY_NAME: s.NAME for s in SOURCES}
    merged = merge_offers(offers, names)
    if limit:
        print_summary(merged)
        return 0  # a partial run must not overwrite the full offer table
    db.replace_offers(conn, merged)
    db.finish_refresh(conn, refresh_id, len(merged))
    print_summary(merged)
    return 0


def print_summary(offers: list[Offer]) -> None:
    by_cat = Counter(o.category for o in offers)
    multi = sum(len(o.sources) > 1 for o in offers)
    flagged = sum(o.needs_verification for o in offers)
    conflicts = sum(bool(o.conflicts) for o in offers)
    print(f"\n{len(offers)} offers after merge ({multi} confirmed by 2+ sources)")
    for cat, n in sorted(by_cat.items()):
        print(f"  {cat:<26} {n:>3}")
    slots = Counter(s for o in offers for s in o.meal_slots if o.category == "Food & Drink")
    print("  meal slots: " + ", ".join(f"{k} {v}" for k, v in sorted(slots.items())))
    print(f"  needs verification: {flagged} (with source conflicts: {conflicts})")


def status(show_keys: bool) -> int:
    conn = db.connect()
    last = db.last_refresh(conn)
    print(ollama_status()[1])
    if last is None:
        print("No refresh yet. Run: uv run python -m vetday.pipeline refresh")
        return 1
    print(f"Last refresh: {last['finished_at']} (mode={last['mode']}, model={last['model']})")
    for s in last["sources"]:
        print(f"  {s['source']:<13} {s['status']:<7} {s['raw_count']:>3} raw  {s['message'] or ''}")
    offers = db.load_offers(conn)
    print_summary(offers)
    if show_keys:
        for o in offers:
            print(f"  {o.brand_key:<40} {o.brand}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="vetday.pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh", help="scrape + extract + merge")
    r.add_argument("--no-llm", action="store_true", help="fast rules-only run")
    r.add_argument("--offline", action="store_true", help="use data/raw/*.html, no requests")
    r.add_argument("--limit", type=int, help="only extract the first N paragraphs (trial run)")
    s = sub.add_parser("status", help="show last refresh and data health")
    s.add_argument("--keys", action="store_true", help="list brand keys (for overrides.yaml)")
    args = parser.parse_args(argv)
    if args.cmd == "refresh":
        return refresh(use_llm=not args.no_llm, offline=args.offline, limit=args.limit)
    return status(args.keys)


if __name__ == "__main__":
    sys.exit(main())
