"""
化安通 (HuaAnTong) - MSDS自动生成系统
应用配置模块 - 使用 pydantic-settings 管理环境变量
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    应用配置

    .env 文件中的环境变量名与字段名完全一致，因此 pydantic-settings
    会自动读取。对于 HUANTONG_ 前缀的变量，直接使用原始名称作为字段名。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ----------------------------------------------------------
    # LLM 配置（OpenAI 兼容接口）
    # ----------------------------------------------------------
    HUANTONG_LLM_PROVIDER: str = "openai"
    HUANTONG_LLM_API_KEY: str = ""
    HUANTONG_LLM_BASE_URL: str = "https://api.openai.com/v1"
    HUANTONG_LLM_MODEL: str = "gpt-4o-mini"

    # ----------------------------------------------------------
    # Anthropic 配置
    # ----------------------------------------------------------
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_BASE_URL: str = "https://api.minimaxi.com/anthropic"
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"

    # ----------------------------------------------------------
    # 数据库
    # ----------------------------------------------------------
    DATABASE_URL: str = "sqlite:///./msds.db"

    # ----------------------------------------------------------
    # 路径（计算属性）
    # ----------------------------------------------------------
    base_dir: Path = Path(__file__).resolve().parent.parent  # backend/

    @property
    def llm_provider(self) -> str:
        return self.HUANTONG_LLM_PROVIDER

    @property
    def llm_api_key(self) -> str:
        return self.HUANTONG_LLM_API_KEY

    @property
    def llm_base_url(self) -> str:
        return self.HUANTONG_LLM_BASE_URL

    @property
    def llm_model(self) -> str:
        return self.HUANTONG_LLM_MODEL

    @property
    def output_dir(self) -> Path:
        path = self.base_dir / "output"
        path.mkdir(exist_ok=True)
        (path / "pure").mkdir(exist_ok=True)
        (path / "mixture").mkdir(exist_ok=True)
        return path

    @property
    def db_dir(self) -> Path:
        path = self.base_dir / "db"
        path.mkdir(exist_ok=True)
        return path

    @property
    def kb_file(self) -> Path:
        return self.db_dir / "chemical_db.json"


settings = Settings()
