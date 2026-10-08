from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "Storefront Fraud Investigator"
    DEBUG: bool = False
    PYTHONUNBUFFERED: str = "1"

    # Postgres
    DB_USER: str = "shop"
    DB_PASSWORD: str = "shop_dev"
    DB_HOST: str = "localhost"
    DB_PORT: int = 5434  # host ports below are this fork's (see docker-compose.yml / CLAUDE.md)
    DB_NAME: str = "shop"  # single database holding every table
    
    # Qdrant
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6335

    # Nebius Token Factory (OpenAI-compatible)
    NEBIUS_API_KEY: str = ""
    NEBIUS_BASE_URL: str = "https://api.tokenfactory.nebius.com/v1/"
    MODEL_AGENT: str = ""  # exact model id from the Token Factory console — no guessed default
    MODEL_FAST: str = ""   # cheaper model for the evaluation judge; empty -> MODEL_AGENT
    MODEL_AGENT_CONTEXT_WINDOW: int = 32768

    # Redis
    REDIS_HOST: str = "localhost" 
    REDIS_PORT: int = 6380 
    REDIS_DB: int = 0 
    REDIS_PASSWORD: str = ""

    # Rate limits for a public demo (0 = off)
    RATE_LIMIT_PER_MINUTE: int = 0  # questions per visitor per minute
    RATE_LIMIT_PER_DAY: int = 0     # questions per day across all visitors


    #! (NOT IN .ENVs)
    
    # ENVIRONMENT 
    ENVIRONMENT: str = "DEVELOPMENT"  # or "PRODUCTION" or "TESTING"

    # INGESTOR
    # where the checkpoint/offset files are kept; empty -> shared/checkpoint in the code
    # tree. A deployment points this at a volume so they survive container recreation.
    CHECKPOINT_DIR: str = ""
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # .env carries a few keys (e.g. old_openai_api_key, bot_token)
                          # unrelated scripts still use — don't hard-fail on those.


settings = Settings()
