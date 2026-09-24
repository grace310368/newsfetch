from newsfetch import keyword_learning, review, rules
from newsfetch.classifier import Suggestion, classify
from newsfetch.extract import Article
from newsfetch.review import FinalItem

N = iter(range(1000, 9999))


def add(conn, title, keywords, topics, origin="crawler", suggestions=None, search_term=None, delete=False):
    n = next(N)
    a = Article(url=f"https://www.ctee.com.tw/news/{n}-1", title=title, source="工商時報",
                published_date="2026-09-10", summary=title, classify_text=title, keywords=keywords)
    if suggestions is None:
        suggestions = [Suggestion(t, "政策與法規", "") for t in topics] if origin == "manual" \
            else classify(title, title, keywords, rules.active_topics(conn))
    review.ingest(conn, a, suggestions, origin, search_term)
    pid = conn.execute("SELECT id FROM pending_review WHERE url = ?", (a.url,)).fetchone()["id"]
    if delete:
        review.delete(conn, pid, "雜訊")
    else:
        review.finalize(conn, pid, [FinalItem(t, "政策與法規", False) for t in topics])
    return pid


def find(result, **kw):
    return [s for s in result["suggestions"] if all(s.get(k) == v for k, v in kw.items())]


def test_topic_gap_suggestion_and_adoption_loop(conn):
    # 規則沒有「以房養老」，但人工兩次都把含此詞的文章歸到全齡金融
    add(conn, "以房養老貸款創新高", ["以房養老", "銀行"], ["全齡金融"])
    add(conn, "壽險推以房養老新方案", ["以房養老", "壽險"], ["全齡金融"])
    add(conn, "台股今日大漲", ["台股"], [], delete=True)

    result = keyword_learning.analyze(conn)
    sug = find(result, kind="topic", topic="全齡金融", term="以房養老")
    assert sug and sug[0]["stats"] == {"support": 2, "gaps": 2, "precision": 1.0}
    assert not find(result, term="台股")          # 籠統標籤排除
    assert not find(result, term="銀行")          # 子分類關鍵字排除

    review.apply_op(conn, {"type": "keyword", "action": "adopt", "kind": "topic", "topic": "全齡金融", "term": "以房養老"})
    assert "以房養老" in rules.active_topics(conn)["全齡金融"]
    assert [s.topic for s in classify("以房養老再升溫", "", "", rules.active_topics(conn))] == ["全齡金融"]
    # 採用後缺口消失，不再建議
    assert not find(keyword_learning.analyze(conn), kind="topic", term="以房養老")


def test_manual_adds_split_into_keyword_gap_and_source_gap(conn):
    add(conn, "以房養老商品熱賣", ["以房養老"], ["全齡金融"], origin="manual")
    add(conn, "TISA開戶數破表", ["TISA"], ["亞洲資產管理中心"], origin="manual")  # 已含搜尋詞 → 來源問題
    add(conn, "以房養老門檻降低", ["以房養老"], ["全齡金融"])

    result = keyword_learning.analyze(conn)
    assert result["missed"]["keyword_gap"] == 1 and result["missed"]["source_gap"] == 1
    seed = find(result, kind="seed", term="以房養老")
    assert seed and seed[0]["stats"]["missed"] == 1 and seed[0]["stats"]["relevant"] == 2

    review.apply_op(conn, {"type": "keyword", "action": "ignore", "kind": "seed", "term": "以房養老"})
    assert not find(keyword_learning.analyze(conn), kind="seed", term="以房養老")
    assert "以房養老" not in rules.active_seed_terms(conn)


def test_misfire_disable_suggestion(conn):
    etf = Suggestion("國際級資本市場", "商品與業務", "", ["ETF"])
    for i in range(3):
        add(conn, f"ETF配息公告{i}", [], [], suggestions=[etf], delete=True)
    result = keyword_learning.analyze(conn)
    sug = find(result, action="disable", kind="topic", term="ETF")
    assert sug and sug[0]["stats"]["misfire_rate"] == 1.0

    review.apply_op(conn, {"type": "keyword", "action": "disable", "kind": "topic", "topic": "國際級資本市場", "term": "ETF"})
    assert "ETF" not in rules.active_topics(conn)["國際級資本市場"]
    assert classify("ETF配息", "", "", rules.active_topics(conn)) == []


def test_seed_term_stats_and_disable(conn):
    for i in range(5):
        add(conn, f"少子化新聞{i}", [], [], search_term="少子化", delete=True)
    add(conn, "少子化衝擊壽險", [], ["全齡金融"], search_term="少子化")
    stats = {s["term"]: s for s in keyword_learning.analyze(conn)["seed_term_stats"]}
    assert (stats["少子化"]["found"], stats["少子化"]["approved"], stats["少子化"]["deleted"]) == (6, 1, 5)
    assert find(keyword_learning.analyze(conn), action="disable", kind="seed", term="少子化")

    review.apply_op(conn, {"type": "keyword", "action": "disable", "kind": "seed", "term": "少子化"})
    assert "少子化" not in rules.active_seed_terms(conn)


def test_invalid_keyword_ops(conn):
    import pytest
    from newsfetch.review import ReviewError

    with pytest.raises(ReviewError):
        review.apply_op(conn, {"type": "keyword", "action": "adopt", "kind": "topic", "topic": "不存在", "term": "x"})
    with pytest.raises(ReviewError):
        review.apply_op(conn, {"type": "keyword", "action": "boom", "kind": "seed", "term": "x"})


def test_broad_seed_does_not_count_as_covered_and_institutions_excluded(conn):
    add(conn, "國銀以房養老核貸衝百億", ["以房養老", "金管會"], ["全齡金融"], origin="manual")
    add(conn, "凱基證金融回饋行動", ["凱基證", "富邦", "金融回饋"], ["金融大回饋"])
    add(conn, "富邦證推金融回饋", ["富邦", "金融回饋"], ["金融大回饋"])
    result = keyword_learning.analyze(conn)
    assert result["missed"]["keyword_gap"] == 1           # 「金管會」太廣，不算已涵蓋
    assert find(result, kind="topic", topic="金融大回饋", term="金融回饋")
    assert not find(result, term="富邦") and not find(result, term="凱基證")
