"""關鍵字庫、議題與子分類規則、路徑設定。

規則字典皆為純字串比對用，不呼叫任何 LLM。擴充關鍵字時只需要修改本檔。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("NEWSFETCH_DB", ROOT / "data" / "news.db"))
DOCS_DIR = Path(os.environ.get("NEWSFETCH_DOCS", ROOT / "docs"))
EXPORT_DIR = Path(os.environ.get("NEWSFETCH_EXPORT", DOCS_DIR / "data"))
LOG_DIR = Path(os.environ.get("NEWSFETCH_LOGS", ROOT / "logs"))

TIMEZONE = "Asia/Taipei"

# 追蹤關鍵字（核心詞 + 擴充詞），每日爬蟲對每個詞呼叫各來源搜尋頁
SEED_TERMS: dict[str, list[str]] = {
    "核心政策詞": [
        "亞洲資產管理中心", "亞資中心",
        "國際級資本市場",
        "三軌金融",
        "全齡金融",
        "信任金融",
        "金融大回饋",
        "金融卓越發展計畫",
    ],
    "亞資中心延伸詞": [
        "高雄資產管理專區", "高雄亞洲新灣區", "台南專區",
        "OBU", "OSU", "OIU", "OAMU", "境外資產管理平臺",
        "TISA", "個人投資儲蓄投資帳戶", "資產管理規模",
        "亞洲創新籌資平台", "台灣週", "私人銀行", "家族辦公室",
        "五大開放政策",
    ],
    "全齡金融延伸詞": [
        "退休第三支柱", "少子化", "高齡化", "普惠金融",
        "銀髮金融", "長照金融",
    ],
    "信任金融延伸詞": [
        "社會信任", "金融共好", "社會負債", "社會信任資產負債表",
        "永續金融", "公司治理", "ESG金融",
    ],
    "人物與機關": [
        "彭金隆", "童政彰", "金管會", "銀行局",
        "金融發展與亞資中心策進會",
    ],
}

# 六大議題（順序即前端分頁順序與標籤色序）
TOPICS: dict[str, list[str]] = {
    "亞洲資產管理中心": [
        "亞洲資產管理中心", "亞資中心", "高雄專區", "高雄資產管理專區",
        "高雄亞洲新灣區", "台南專區", "OBU", "OSU", "OIU", "OAMU",
        "境外資產管理平臺", "TISA", "個人投資儲蓄投資帳戶",
        "資產管理規模", "亞洲創新籌資平台", "台灣週", "私人銀行",
        "家族辦公室", "五大開放政策",
    ],
    "國際級資本市場": [
        "國際級資本市場", "亞洲創新籌資平台", "上市櫃制度", "ETF",
        "跨境合作", "國際板",
    ],
    "三軌金融": ["三軌金融"],
    "全齡金融": [
        "全齡金融", "退休第三支柱", "少子化", "高齡化", "銀髮金融",
        "長照金融", "普惠金融",
    ],
    "信任金融": [
        "信任金融", "社會信任", "金融共好", "社會負債",
        "社會信任資產負債表", "永續金融", "公司治理", "ESG金融",
    ],
    "金融大回饋": ["金融大回饋"],
}

# 子分類（dict 順序即優先序：政策與法規 > 商品與業務 > 同業動態）
SUBCATEGORIES: dict[str, list[str]] = {
    "政策與法規": [
        "金管會", "法規", "鬆綁", "政策", "修法", "草案", "函釋",
        "核准", "試辦", "展延", "許可", "規範", "辦法",
    ],
    "商品與業務": [
        "商品", "業務", "推出", "上線", "開戶", "申購", "基金",
        "保單", "信託", "理財", "帳戶", "平台",
    ],
    "同業動態": [
        "金控", "銀行", "業者", "簽署", "合作", "MOU", "招商",
        "說明會", "布局", "進軍", "設立",
    ],
}

TOPIC_NAMES = list(TOPICS)
SUBCATEGORY_NAMES = list(SUBCATEGORIES)

# 月度報告欄位與子分類的對應
SUBCATEGORY_REPORT_FIELDS = {
    "政策與法規": "policy_report",
    "商品與業務": "product_report",
    "同業動態": "peer_report",
}

SOURCE_CTEE = "工商時報"
SOURCE_UDN = "經濟日報"

# 爬蟲參數
REQUEST_DELAY_RANGE = (1.0, 2.0)   # 每次請求間隔秒數（禮貌爬取）
REQUEST_TIMEOUT = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
LOOKBACK_DAYS = int(os.environ.get("NEWSFETCH_LOOKBACK_DAYS", "2"))  # 容忍 cron 延遲
MAX_RESULTS_PER_TERM = int(os.environ.get("NEWSFETCH_MAX_PER_TERM", "20"))
MAX_FETCH_ATTEMPTS = 3              # 單篇文章抓取失敗的重試上限（跨日累計）

SUMMARY_STORE_LEN = 150   # 資料庫只存前 150 字
SUMMARY_CLASSIFY_LEN = 200  # 分類時參考前 200 字

STATS_WINDOW_DAYS = 30


def all_seed_terms() -> list[str]:
    seen: dict[str, None] = {}
    for terms in SEED_TERMS.values():
        for t in terms:
            seen.setdefault(t, None)
    return list(seen)
