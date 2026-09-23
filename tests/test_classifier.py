from newsfetch.classifier import classify, classify_for_topics, find_terms


def topics_of(sugs):
    return {s.topic: s.subcategory for s in sugs}


def test_multi_topic_with_independent_subcategories():
    sugs = classify(
        "亞資中心助攻　東方匯理進軍台灣ETF",
        "外資資產管理業者宣布進軍台灣ETF市場，看好亞資中心政策帶動的資金動能。",
    )
    got = topics_of(sugs)
    assert set(got) == {"亞洲資產管理中心", "國際級資本市場"}
    assert all(s.reason.startswith("命中關鍵字") for s in sugs)


def test_keywords_take_priority_and_reason_mentions_field():
    sugs = classify("某新聞標題", "", keywords="TISA,理財")
    assert sugs[0].topic == "亞洲資產管理中心"
    assert "（標籤）" in sugs[0].reason


def test_subcategory_priority_policy_over_peer():
    # 同時命中「金管會／核准」（政策）與「銀行」（同業）→ 政策與法規
    sugs = classify("金管會核准銀行試辦TISA新制", "")
    assert topics_of(sugs)["亞洲資產管理中心"] == "政策與法規"


def test_subcategory_context_per_topic():
    title = "信任金融論壇登場"
    summary = "主委強調信任金融要修法落實。另外，多家金控宣布合作推出ETF。"
    got = topics_of(classify(title, summary))
    assert got["信任金融"] == "政策與法規"      # 上下文有「修法」
    assert got["國際級資本市場"] == "商品與業務"  # ETF 附近是「推出」（商品）優先於「合作」


def test_subcategory_none_when_no_hits():
    got = topics_of(classify("三軌金融是什麼", ""))
    assert got == {"三軌金融": None}


def test_no_topic_returns_empty():
    assert classify("台股今日收盤上漲", "電子股領漲") == []


def test_ascii_terms_are_whole_word_and_case_insensitive():
    assert find_terms("新設obu分行", ["OBU"]) == ["OBU"]
    assert find_terms("ROBUST 系統", ["OBU"]) == []
    assert find_terms("TISA上路", ["TISA"]) == ["TISA"]


def test_manual_topics():
    sugs = classify_for_topics(["全齡金融", "信任金融"], "銀行推出銀髮信託商品", "")
    assert [s.topic for s in sugs] == ["全齡金融", "信任金融"]
    assert all(s.subcategory == "商品與業務" for s in sugs)
    assert all("使用者手動指定" in s.reason for s in sugs)
