from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

engine = create_engine("sqlite:///./todo.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Todo(Base):
    __tablename__ = "todos"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    overdue: Mapped[bool] = mapped_column(Boolean, default=False)


def initialize() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        if session.scalar(select(Todo.id).limit(1)) is None:
            session.add_all(
                [
                    Todo(title="샘플 앱 실행 확인", due_at=datetime(2020, 1, 1)),
                    Todo(title="배포 설정 검토", due_at=datetime(2099, 1, 1)),
                ]
            )
            session.commit()
