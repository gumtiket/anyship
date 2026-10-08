from pathlib import Path
from dotenv import load_dotenv
from .app import create_app
from .config import Settings

load_dotenv(Path(__file__).resolve().parents[1] / ".env.github.local")
app = create_app(Settings.from_env())
