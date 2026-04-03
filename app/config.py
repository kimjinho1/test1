from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # KIS API
    kis_app_key: str = ""
    kis_app_secret: str = ""
    kis_account_no: str = ""
    kis_is_virtual: bool = True

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    # Risk Controls
    max_position_pct: float = 10.0
    stop_loss_pct: float = 3.0
    daily_loss_limit_pct: float = 5.0

    # Strategy
    strategy_eval_interval_sec: int = 60

    # Market Hours (KST)
    market_open_hour: int = 9
    market_open_minute: int = 0
    market_close_hour: int = 15
    market_close_minute: int = 30

    # Database
    database_url: str = "sqlite:///./trading.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
