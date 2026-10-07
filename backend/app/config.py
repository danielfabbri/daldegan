from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ANU_DEFAULT_ENDPOINT = "https://api.quantumnumbers.anu.edu.au"


class Settings(BaseSettings):
    """Configuração lida de variáveis de ambiente (prefixo DALDEGAN_) ou de .env."""

    model_config = SettingsConfigDict(env_prefix="DALDEGAN_", env_file=".env", extra="ignore")

    qrng_api_key: str | None = None
    qrng_endpoint: str = ANU_DEFAULT_ENDPOINT
    qrng_timeout_s: float = 30.0
    qrng_data_type: str = "uint8"
    # Plano gratuito da ANU: 1 requisição por segundo.
    qrng_min_interval_s: float = 1.1
    data_dir: Path = Path("./data")
    show_full_hash: bool = True

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def test_sessions_dir(self) -> Path:
        return self.data_dir / "sessions_test"

    @property
    def global_audit_path(self) -> Path:
        return self.data_dir / "audit" / "sessions.log"

    @property
    def index_db_path(self) -> Path:
        return self.data_dir / "daldegan.db"
