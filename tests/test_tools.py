"""工具函数测试"""
from app.tools import _format_results


def test_format_results_empty():
    assert _format_results([]) == ""


def test_format_results():
    results = [{"title": "Test", "body": "Content", "href": "https://example.com"}]
    output = _format_results(results)
    assert "[1] Test" in output
    assert "Content" in output
    assert "example.com" in output
