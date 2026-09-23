import pytest

from newsfetch.extract import is_article_url, normalize_url, parse_article_html, parse_datetime, source_for_url
from newsfetch.http import EMPTY_FIELDS, NOT_SUPPORTED, FetchError
from newsfetch.sources import extract_article_links

from .conftest import fixture_html


def test_parse_ctee_article():
    a = parse_article_html(fixture_html("ctee_article.html"), "https://www.ctee.com.tw/news/20260915700123-430101?x=1")
    assert a.url == "https://www.ctee.com.tw/news/20260915700123-430101"
    assert a.source == "工商時報"
    assert a.title == "亞資高雄專區試辦業務展延　金管會三叮囑"
    assert (a.published_date, a.published_time) == ("2026-09-15", "16:20")
    assert a.keywords == ["亞資中心", "高雄專區", "金管會", "彭金隆"]
    assert 0 < len(a.summary) <= 150
    assert len(a.classify_text) <= 200


def test_parse_udn_article():
    a = parse_article_html(fixture_html("udn_article.html"), "https://money.udn.com/money/story/5613/8123456")
    assert a.source == "經濟日報"
    assert a.title.startswith("彭金隆：信任金融")
    assert "經濟日報" not in a.title
    assert (a.published_date, a.published_time) == ("2026-09-15", "10:42")
    assert a.keywords == ["信任金融", "彭金隆", "公司治理"]


def test_missing_fields_flagged():
    with pytest.raises(FetchError) as e:
        parse_article_html("<html><body><p>空白</p></body></html>", "https://www.ctee.com.tw/news/1-2")
    assert e.value.category == EMPTY_FIELDS


def test_unsupported_site():
    with pytest.raises(FetchError) as e:
        parse_article_html("<html></html>", "https://example.com/news/1")
    assert e.value.category == NOT_SUPPORTED


def test_url_helpers():
    assert normalize_url("http://m.udn.com/news/story/7238/123/?ref=a#x") == "https://udn.com/news/story/7238/123"
    assert source_for_url("https://money.udn.com/money/story/1/2") == "經濟日報"
    assert is_article_url("https://www.ctee.com.tw/news/20260915700123-430101")
    assert is_article_url("https://money.udn.com/money/story/5613/8123456")
    assert is_article_url("https://udn.com/news/story/7238/8123456")
    assert not is_article_url("https://www.ctee.com.tw/search/TISA")
    assert not is_article_url("https://udn.com/news/cate/2/6644")


def test_parse_datetime_formats():
    assert parse_datetime("2026-09-15T08:20:00Z") == ("2026-09-15", "16:20")
    assert parse_datetime("2026/09/15 10:42") == ("2026-09-15", "10:42")
    assert parse_datetime("2026年9月5日") == ("2026-09-05", None)
    assert parse_datetime("") is None


def test_extract_search_links():
    links = extract_article_links(fixture_html("ctee_search.html"), "https://www.ctee.com.tw/search/TISA")
    assert links == [
        "https://www.ctee.com.tw/news/20260915700123-430101",
        "https://www.ctee.com.tw/news/20260915700456-430101",
        "https://www.ctee.com.tw/news/20260914700789-430301",
    ]


def test_udn_title_channel_suffix_removed():
    html = ('<html><head><meta property="og:title" content="TISA 總規模 倍數成長 | 基金天地 | 理財 | 經濟日報">'
            '<meta name="date" content="2026/09/16 23:20:00"></head><body></body></html>')
    a = parse_article_html(html, "https://money.udn.com/money/story/5613/1")
    assert a.title == "TISA 總規模 倍數成長"


def test_search_links_limited_to_result_container():
    html = ('<div class="swiper-slide"><a href="/money/story/1/111">跑馬燈</a></div>'
            '<div class="story__content"><a href="/money/story/2/222">TISA 結果</a></div>')
    assert extract_article_links(html, "https://money.udn.com/search/result/1001/TISA",
                                 containers=(".story__content",)) == ["https://money.udn.com/money/story/2/222"]
    # 找不到結果區塊（改版）時退回整頁
    assert len(extract_article_links(html, "https://money.udn.com/", containers=(".nope",))) == 2
