from sqlalchemy import BigInteger, ForeignKey, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    login: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))


class Membership(Base):
    __tablename__ = "memberships"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), default="owner")


class LoginSession(Base):
    __tablename__ = "login_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    token_cipher: Mapped[str] = mapped_column(Text)
    csrf: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)


class OAuthAttempt(Base):
    __tablename__ = "oauth_attempts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    browser_hash: Mapped[str] = mapped_column(String(64))
    verifier: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("workspace_id", "repository_id", name="uq_project_workspace_repository"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    repository_id: Mapped[int] = mapped_column(BigInteger)
    installation_id: Mapped[int] = mapped_column(BigInteger)
    full_name: Mapped[str] = mapped_column(String(512))
    branch: Mapped[str] = mapped_column(String(255))
    base_sha: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[int] = mapped_column(BigInteger)


class RepositoryConnection(Base):
    __tablename__ = "repository_connections"
    __table_args__ = (UniqueConstraint("user_id", "workspace_id", name="uq_connection_user_workspace"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    repository_url: Mapped[str] = mapped_column(String(2048))
    expires_at: Mapped[int] = mapped_column(BigInteger)
    install_state_hash: Mapped[str] = mapped_column(String(64), default="")
    install_expires_at: Mapped[int] = mapped_column(BigInteger, default=0)


class CodeChange(Base):
    __tablename__ = "code_changes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="proposed")
    base_sha: Mapped[str] = mapped_column(String(64))
    base_tree: Mapped[str] = mapped_column(String(64))
    branch: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    diff: Mapped[str] = mapped_column(Text, default="")
    review_hash: Mapped[str] = mapped_column(String(64), default="")
    tree_sha: Mapped[str] = mapped_column(String(64), default="")
    commit_sha: Mapped[str] = mapped_column(String(64), default="")
    pr_url: Mapped[str] = mapped_column(Text, default="")
    pr_number: Mapped[int] = mapped_column(BigInteger, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    lease_until: Mapped[int] = mapped_column(BigInteger, default=0)


class DemoChange(Base):
    __tablename__ = "demo_changes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="proposed")
    content: Mapped[str] = mapped_column(Text)
    diff: Mapped[str] = mapped_column(Text, default="")
    review_hash: Mapped[str] = mapped_column(String(64), default="")
    commit_sha: Mapped[str] = mapped_column(String(64), default="")
    error: Mapped[str] = mapped_column(Text, default="")


def database(url):
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {}, pool_pre_ping=True)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine, sessionmaker(engine, expire_on_commit=False)
