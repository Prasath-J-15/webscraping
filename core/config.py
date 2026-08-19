import sys

from pydantic_settings import BaseSettings, SettingsConfigDict

_WINDOWS = sys.platform == "win32"


class Settings(BaseSettings):
    """Application configuration loaded from environment variables.

    Elasticsearch fields are given empty defaults (rather than being required)
    so this demo runs end-to-end with no ES cluster — see db/elasticsearch_client.py.
    """

    elasticsearch_host: str = ""
    elasticsearch_username: str = ""
    elasticsearch_password: str = ""

    log_level: str = "INFO"
    environment: str = "development"
    index_name: str = "learning_scraped_items"

    playwright_timeout_ms: int = 30_000
    playwright_render_wait_ms: int = 8_000

    # On Windows, headless Chromium is frequently blocked by local firewall/AV
    # network filtering while headful is permitted — so default headful there.
    # On Linux/CI, default headless (no display available). Override either
    # way via the env vars below.
    playwright_headless: bool = not _WINDOWS
    playwright_channel: str = ""

    test_mode: bool = True
    test_mode_job_limit: int = 5

    # Restart the browser after this many detail pages in click-through
    # crawlers — bounds memory growth across a long paginated crawl.
    browser_restart_after_pages: int = 5
    # Reload attempts when a detail page returns empty/too-small content.
    empty_page_max_retries: int = 3

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
