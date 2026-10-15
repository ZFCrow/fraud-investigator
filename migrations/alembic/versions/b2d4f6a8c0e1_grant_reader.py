"""grant the read-only role SELECT on the store tables

The agent's SQL tool connects as shop_reader (settings.DB_READER_USER). The role itself is
created by db_init/03_create_users.sh, because creating a role needs a superuser and
migrations run as the app user; the table grants are here because the tables are created
by migrations and owned by the app user.

Only the store tables are granted. The app's own tables (agent_trace, prompt, evaluation)
stay unreadable to the agent.

Revision ID: b2d4f6a8c0e1
Revises: 7e4a0799316f
Create Date: 2026-10-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b2d4f6a8c0e1'
down_revision: Union[str, Sequence[str], None] = '7e4a0799316f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

READER = "shop_reader"
STORE_TABLES = ", ".join(f"shop.{t}" for t in (
    "customers", "products", "promo_codes", "sessions", "events",
    "orders", "order_items", "payment_attempts", "refunds",
))


def upgrade() -> None:
    """Upgrade schema."""
    exists = op.get_bind().scalar(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": READER})
    if not exists:
        # a database volume created before the role was added to db_init: see the readme
        # ("Development notes") for the one-time statements that create it
        raise RuntimeError(f"role {READER} does not exist -- create it as the Postgres superuser first")
    op.execute(f"GRANT SELECT ON {STORE_TABLES} TO {READER}")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"REVOKE SELECT ON {STORE_TABLES} FROM {READER}")
