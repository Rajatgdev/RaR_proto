"""Apply .sql migrations in order, on the DIRECT (non-pooled) Neon URL.

Run as a one-off, not on app startup:  python -m db.migrate
"""
import glob
import os

import psycopg

from config import settings


def main() -> None:
    here = os.path.dirname(__file__)
    files = sorted(glob.glob(os.path.join(here, "*.sql")))
    with psycopg.connect(settings.DATABASE_URL_DIRECT) as conn:
        for path in files:
            with open(path) as f:
                conn.execute(f.read())
            print(f"applied {os.path.basename(path)}")
        conn.commit()


if __name__ == "__main__":
    main()
