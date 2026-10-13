"""Explicit database and authentication configuration."""
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    sql_url: str = 'mysql+pymysql://hawkerflow:hawkerflow_dev@127.0.0.1:3307/hawkerflow'
    mongo_url: str = 'mongodb://127.0.0.1:27018'
    mongo_database: str = 'hawkerflow'
    secret_key: str = 'local-demo-only-change-this-before-sharing-network'
    token_minutes: int = 60

settings = Settings()
