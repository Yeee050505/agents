"""工具函数测试"""
from app.tools import needs_realtime_search, is_stale_response, _format_results


def test_needs_realtime_search():
    assert needs_realtime_search("今天的热点话题") is True
    assert needs_realtime_search("最新新闻") is True
    assert needs_realtime_search("帮我写一首诗") is False
    assert needs_realtime_search("什么是Python") is False


def test_is_stale_response():
    assert is_stale_response("我的知识截止于2024年") is True
    assert is_stale_response("无法获取实时信息") is True
    assert is_stale_response("今天天气很好") is False
    assert is_stale_response("这是一个完整的回答") is False


def test_format_results_empty():
    assert _format_results([]) == ""


def test_format_results():
    results = [{"title": "Test", "body": "Content", "href": "https://example.com"}]
    output = _format_results(results)
    assert "[1] Test" in output
    assert "Content" in output
    assert "example.com" in output
