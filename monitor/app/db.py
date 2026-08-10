import os

from sqlalchemy import create_engine

DEFAULT_DB_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/postgres"

_db_url = os.environ.get("MONITOR_DB_CONNECTION_URI", DEFAULT_DB_URL)

# Read-only is enforced at the session level (not just by convention):
# every connection opens with default_transaction_read_only=on, so any
# accidental write is rejected by Postgres itself.
engine = create_engine(
    _db_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    connect_args={"options": "-c default_transaction_read_only=on"},
)
