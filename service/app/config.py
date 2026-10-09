import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from sqlalchemy.engine import make_url

from .aws_validation import validate_aws_settings

DEFAULT_DATABASE_URL = "postgresql+psycopg://anyship@127.0.0.1:55432/anyship"


@dataclass(frozen=True)
class Settings:
    app_origin: str = "http://localhost:8000"
    database_url: str = field(default=DEFAULT_DATABASE_URL, repr=False)
    github_client_id: str = ""
    github_client_secret: str = field(default="", repr=False)
    github_app_slug: str = ""
    token_key: str = field(default="", repr=False)
    demo: bool = False
    ai_mode: str = "unavailable"
    production: bool = False
    deployment_mode: str = "unavailable"
    mock_step_delay: float = 0.3
    aws_template_url: str = field(default="", repr=False)
    aws_service_role_arn: str = ""
    aws_regions: tuple[str, ...] = ()
    aws_role_name: str = "deploy-service-role"
    aws_verify: str = ""  # "sts"면 환경 등록의 연결 확인에 STSAdapter를 쓴다. 기본은 꺼짐(어댑터 연결 대기)
    frontend_dist: Path = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    demo_workspaces: Path = Path(__file__).resolve().parents[1] / "workspaces" / "demo"

    def __post_init__(self):
        if self.deployment_mode not in ("unavailable", "mock"):
            raise ValueError("APP_DEPLOYMENT_MODE must be unavailable or mock.")
        if self.production and self.deployment_mode == "mock":
            raise ValueError("Mock deployments are only available in development.")
        if not 0 <= self.mock_step_delay <= 2:
            raise ValueError("APP_MOCK_STEP_DELAY must be between 0 and 2 seconds.")
        validate_aws_settings(self.aws_template_url, self.aws_service_role_arn, self.aws_regions)
        if not re.fullmatch(r"[A-Za-z0-9_+=,.@-]{1,64}", self.aws_role_name.replace("{id}", "0" * 32)):
            raise ValueError("APP_AWS_ROLE_NAME must be an IAM role name, optionally containing {id}.")
        if self.aws_verify not in ("", "sts"):
            raise ValueError("APP_AWS_VERIFY must be empty or sts.")
        if self.ai_mode not in ("placeholder", "unavailable"):
            raise ValueError("APP_AI_MODE must be placeholder or unavailable.")
        if self.production and self.ai_mode == "placeholder":
            raise ValueError("AI placeholder is only available in development.")
        origin = urlsplit(self.app_origin)
        if origin.scheme not in ("http", "https") or not origin.netloc or origin.path or origin.query or origin.fragment:
            raise ValueError("APP_APP_ORIGIN must be an origin without a trailing slash.")
        if self.production and (self.demo or origin.scheme != "https" or make_url(self.database_url).get_backend_name() != "postgresql"):
            raise ValueError("Production requires HTTPS, PostgreSQL and demo disabled.")
        if not self.demo and not self.token_key:
            raise ValueError("Set APP_TOKEN_KEY before starting real authentication.")
        if self.github_app_slug and not re.fullmatch(r"[A-Za-z0-9-]+", self.github_app_slug):
            raise ValueError("APP_GITHUB_APP_SLUG must be a GitHub App slug.")
        if self.production and not self.github_configured:
            raise ValueError("Production requires GitHub App configuration.")

    @property
    def aws_setup_issues(self):
        # Expose only missing setting names, never role, template or credential values.
        required = {"template": self.aws_template_url, "service_role": self.aws_service_role_arn,
                    "regions": self.aws_regions, "live_mode": not self.demo}
        return [name for name, value in required.items() if not value]

    @property
    def aws_configured(self):
        return not self.aws_setup_issues

    @property
    def github_configured(self):
        return bool(self.github_client_id and self.github_client_secret and self.github_app_slug)

    @property
    def secure_cookies(self):
        return self.app_origin.startswith("https://")

    @classmethod
    def from_env(cls):
        return cls(
            app_origin=os.getenv("APP_APP_ORIGIN", "http://localhost:8000"),
            database_url=os.getenv("APP_DATABASE_URL") or DEFAULT_DATABASE_URL,
            github_client_id=os.getenv("APP_GITHUB_CLIENT_ID", ""),
            github_client_secret=os.getenv("APP_GITHUB_CLIENT_SECRET", ""),
            github_app_slug=os.getenv("APP_GITHUB_APP_SLUG", ""),
            token_key=os.getenv("APP_TOKEN_KEY", ""),
            demo=os.getenv("APP_DEMO", "false").lower() == "true",
            ai_mode=os.getenv("APP_AI_MODE", "unavailable"),
            production=os.getenv("APP_ENV", "development") == "production",
            deployment_mode=os.getenv("APP_DEPLOYMENT_MODE", "unavailable"),
            mock_step_delay=float(os.getenv("APP_MOCK_STEP_DELAY", "0.3")),
            aws_template_url=os.getenv("APP_AWS_TEMPLATE_URL", "").strip(),
            aws_service_role_arn=os.getenv("APP_AWS_SERVICE_ROLE_ARN", "").strip(),
            aws_regions=tuple(dict.fromkeys(r.strip() for r in os.getenv("APP_AWS_REGIONS", "").split(",") if r.strip())),
            aws_role_name=os.getenv("APP_AWS_ROLE_NAME", "deploy-service-role").strip(),
            aws_verify=os.getenv("APP_AWS_VERIFY", "").strip().lower(),
        )
