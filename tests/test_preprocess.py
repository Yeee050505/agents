"""文本预处理测试"""
from app.rag.preprocess import clean_text, clean_chunks


def test_clean_text():
    assert clean_text("  hello  ") == "hello"
    assert clean_text("  ") == ""
    assert clean_text("a\n\n\nb") == "a\n\nb"
    assert clean_text("a\u3000b\xa0c") == "a b c"
    assert clean_text("\u0000abc\u0001") == "abc"


def test_clean_chunks():
    chunks = ["hello world", "  python code  ", "", "   ", "a"]
    result = clean_chunks(chunks)
    assert "hello world" in result
    assert "python code" in result
    assert "" not in result
    assert "a" not in result


def test_clean_chunks_short_filter():
    chunks = ["a", "ab", "abc def long enough"]
    result = clean_chunks(chunks)
    assert "abc def long enough" in result
    assert "a" not in result
    assert "ab" not in result


def test_clean_chunks_garbage():
    chunks = ["1234567890123", "----------", "*******", "纯文本内容测试段落不少于十字"]
    result = clean_chunks(chunks)
    assert "纯文本内容测试段落不少于十字" in result
    assert "1234567890123" not in result
    assert "----------" not in result
