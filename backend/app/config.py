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
    SERP_API_KEY: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
