"""全局测试配置"""
import pytest
from app.config import settings


@pytest.fixture(autouse=True)
def setup_env():
    """确保测试环境配置正确"""
    assert settings.DEBUG is True
    yield
