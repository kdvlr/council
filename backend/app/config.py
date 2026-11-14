import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from repo root or current working directory if present
_repo_env = Path(__file__).resolve().parents[2] / ".env"
if _repo_env.exists():
    load_dotenv(_repo_env)
else:
    load_dotenv()


class Settings:
    def __init__(self) -> None:
        raw_url = os.getenv("LITELLM_BASE_URL", "http://localhost:4000/v1").rstrip("/")
        if raw_url.endswith("/v1"):
            self.litellm_v1_url = raw_url
            self.litellm_root_url = raw_url[:-3]
        else:
            self.litellm_root_url = raw_url
            self.litellm_v1_url = f"{raw_url}/v1"

        self.litellm_api_key = os.getenv("LITELLM_API_KEY", "")
        self.data_dir = Path(os.getenv("COUNCIL_DATA_DIR", "./data")).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "council.db"

        patterns = os.getenv(
            "COUNCIL_EXCLUDED_MODEL_PATTERNS",
            "embedding,tts,transcribe,whisper,ocr,moderation,rerank,image",
        )
        self.excluded_patterns = [
            p.strip().lower() for p in patterns.split(",") if p.strip()
        ]


settings = Settings()
