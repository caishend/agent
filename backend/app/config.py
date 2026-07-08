from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # 数据库
    MYSQL_URL: str = "mysql+pymysql://root:password@localhost:3306/skyguard"
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "password"

    # LLM
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o"

    # JWT
    SECRET_KEY: str = "change-this-secret-key"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # 文件存储
    UPLOAD_DIR: str = "data/uploads"
    REPORT_DIR: str = "data/reports"

    # 搜索
    BOCHA_API_KEY: str = ""
    BOCHA_API_URL: str = "https://api.bocha.cn/v1/web-search"
    SERP_API_KEY: str = ""

    # 邮件 / SMTP
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_FROM_NAME: str = "SkyGuard"
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    SMTP_TIMEOUT_SECONDS: float = 10.0

    class Config:
        env_file = ".env"

settings = Settings()
