"""Configuration loaded from environment variables / .env file."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Platform — "gitlab" or "github"
    platform: str = "gitlab"

    # GitLab
    gitlab_url: str = "https://gitlab.com"
    gitlab_token: str = ""
    gitlab_project_id: str = ""

    # GitHub
    github_url: str = "https://api.github.com"
    github_token: str = ""
    # Format: "owner/repo", e.g. "myorg/myrepo"
    github_repo: str = ""

    # PostgreSQL + pgvector
    database_url: str = "postgresql://cr_learner:cr_learner@localhost:5432/cr_learner"

    # Anthropic (used for lesson extraction and embeddings via voyage)
    anthropic_api_key: str = ""

    # Embeddings — by default we use Anthropic's voyage-code-2 via their API.
    # Set to "local" to use a local sentence-transformers model instead.
    embedding_provider: str = "anthropic"
    embedding_model: str = "voyage-code-2"
    embedding_dim: int = 1536

    # Retrieval
    retrieval_top_k: int = 5

    # Scoring
    time_decay_lambda: float = 0.005  # per-day decay; half-life ≈ 139 days
    authority_weights: dict[str, float] = {}  # domain → 0..1, default 0.5

    # Webhook
    webhook_secret: str = ""
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8080

    # LLM model used for lesson extraction
    llm_model: str = "claude-3-5-sonnet-20241022"

    def authority_for(self, domain: str) -> float:
        """Return authority weight for a domain, defaulting to 0.5."""
        return self.authority_weights.get(domain, 0.5)

    @property
    def default_project_id(self) -> str:
        """Return the default project/repo identifier for the configured platform."""
        if self.platform == "github":
            return self.github_repo
        return self.gitlab_project_id


settings = Settings()
