import pytest

from core.config import settings


@pytest.fixture(autouse=True)
def _test_mode_defaults():
    """Keep TEST_MODE on and the job cap small for every test, regardless of .env."""
    original_test_mode, original_limit = settings.test_mode, settings.test_mode_job_limit
    settings.test_mode = True
    settings.test_mode_job_limit = 3
    yield
    settings.test_mode = original_test_mode
    settings.test_mode_job_limit = original_limit
