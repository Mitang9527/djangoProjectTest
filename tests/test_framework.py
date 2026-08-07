"""
工具模块单元测试
"""
import pytest
from datetime import datetime, timedelta

from framework.helpers.time_utils import count_milliseconds, nowtime


@pytest.mark.unit
class TestTimeUtils:
    """时间工具测试"""

    def test_count_milliseconds_basic(self):
        start = datetime(2026, 7, 17, 10, 0, 0)
        end = datetime(2026, 7, 17, 10, 0, 5)
        result = count_milliseconds(start, end)
        assert result == 5000

    def test_count_milliseconds_zero(self):
        now = datetime.now()
        result = count_milliseconds(now, now)
        assert result == 0

    def test_count_milliseconds_subsecond(self):
        start = datetime(2026, 1, 1, 0, 0, 0)
        end = datetime(2026, 1, 1, 0, 0, 0, 500000)  # 0.5 秒
        result = count_milliseconds(start, end)
        assert result == 500

    def test_count_milliseconds_large(self):
        start = datetime(2026, 1, 1, 0, 0, 0)
        end = datetime(2026, 1, 1, 1, 0, 0)  # 1 小时
        result = count_milliseconds(start, end)
        assert result == 3600000

    def test_nowtime_returns_string(self):
        result = nowtime()
        assert isinstance(result, str)
        assert len(result) > 0
