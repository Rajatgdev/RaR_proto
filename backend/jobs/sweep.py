"""Railway Cron entry (second service, same repo). Runs ~every 5 min.

Phase 5 fills this in: claim a bounded batch of due rows in a transaction,
expire holds, dispatch due follow-ups with an idempotency key, then exit.
Stub for now so the service wiring exists.
"""


def main() -> None:
    print("sweep: nothing to do yet (Phase 5)")


if __name__ == "__main__":
    main()
