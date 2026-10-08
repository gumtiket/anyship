import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update

from app.db import SessionLocal, Todo, engine, initialize

SECRET_KEY = "dummy-secret-do-not-use"
logger = logging.getLogger(__name__)


def mark_overdue() -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    with SessionLocal() as session:
        session.execute(
            update(Todo).where(Todo.done.is_(False), Todo.due_at < now).values(overdue=True)
        )
        session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    handler = logging.FileHandler("app.log")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    scheduler = BackgroundScheduler()
    try:
        initialize()
        scheduler.add_job(mark_overdue, "interval", minutes=1, id="mark-overdue", max_instances=1)
        scheduler.start()
        app.state.scheduler = scheduler
        yield
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=True)
        logger.removeHandler(handler)
        handler.close()
        engine.dispose()


app = FastAPI(title="Bronze Todo Scheduler Sample", lifespan=lifespan)


class TodoInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    done: bool = False
    due_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def trim_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("제목은 비어 있을 수 없습니다.")
        return value

    @field_validator("due_at")
    @classmethod
    def normalize_deadline(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is not None:
            return value.astimezone(UTC).replace(tzinfo=None)
        return value


class TodoOutput(TodoInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    overdue: bool


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (Path(__file__).parent / "index.html").read_text(encoding="utf-8")


@app.get("/todos", response_model=list[TodoOutput])
def list_todos() -> list[TodoOutput]:
    with SessionLocal() as session:
        return [
            TodoOutput.model_validate(todo)
            for todo in session.scalars(select(Todo).order_by(Todo.id))
        ]


@app.post("/todos", response_model=TodoOutput, status_code=201)
def create_todo(payload: TodoInput) -> TodoOutput:
    with SessionLocal() as session:
        todo = Todo(**payload.model_dump())
        session.add(todo)
        session.commit()
        session.refresh(todo)
        logger.info("todo created id=%s", todo.id)
        return TodoOutput.model_validate(todo)


@app.put("/todos/{todo_id}", response_model=TodoOutput)
def update_todo(todo_id: int, payload: TodoInput) -> TodoOutput:
    with SessionLocal() as session:
        todo = session.get(Todo, todo_id)
        if todo is None:
            raise HTTPException(404, "할 일이 없습니다.")
        for key, value in payload.model_dump().items():
            setattr(todo, key, value)
        todo.overdue = bool(
            todo.due_at and not todo.done and todo.due_at < datetime.now(UTC).replace(tzinfo=None)
        )
        session.commit()
        session.refresh(todo)
        return TodoOutput.model_validate(todo)


@app.delete("/todos/{todo_id}", status_code=204)
def delete_todo(todo_id: int) -> Response:
    with SessionLocal() as session:
        todo = session.get(Todo, todo_id)
        if todo is None:
            raise HTTPException(404, "할 일이 없습니다.")
        session.delete(todo)
        session.commit()
    return Response(status_code=204)


@app.post("/export")
def export_todos() -> dict[str, str]:
    destination = Path("./data/todos.json")
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(
        json.dumps([t.model_dump(mode="json") for t in list_todos()], ensure_ascii=False),
        encoding="utf-8",
    )
    return {"file": "./data/todos.json"}


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
