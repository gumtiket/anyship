from pathlib import Path
from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool
from app.db import Base
import os

load_dotenv(Path(__file__).resolve().parents[1] / ".env.github.local")
url = os.getenv("APP_DATABASE_URL", "sqlite:///./app.db")
if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
