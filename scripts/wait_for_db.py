from __future__ import annotations

import os
import time


def main() -> None:
    if os.getenv("DJANGO_USE_SQLITE", "0").lower() in {"1", "true", "yes", "on"}:
        return

    import psycopg

    attempts = int(os.getenv("DB_WAIT_ATTEMPTS", "30"))
    delay = float(os.getenv("DB_WAIT_DELAY", "1"))
    connection_params = {
        "dbname": os.getenv("POSTGRES_DB", "crm"),
        "user": os.getenv("POSTGRES_USER", "crm_user"),
        "password": os.getenv("POSTGRES_PASSWORD", "crm_password"),
        "host": os.getenv("POSTGRES_HOST", "db"),
        "port": os.getenv("POSTGRES_PORT", "5432"),
        "connect_timeout": 3,
    }

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with psycopg.connect(**connection_params):
                print("Database is ready.")
                return
        except psycopg.OperationalError as exc:
            last_error = exc
            print(f"Waiting for database ({attempt}/{attempts})...")
            time.sleep(delay)

    raise SystemExit(f"Database is not ready: {last_error}")


if __name__ == "__main__":
    main()
