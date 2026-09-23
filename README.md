# 新聞觀測站：台灣金融政策新聞儀表板

每日自動爬取「工商時報」「經濟日報」，追蹤金管會「金融卓越發展計畫」六大議題
（亞洲資產管理中心、國際級資本市場、三軌金融、全齡金融、信任金融、金融大回饋）。
需求規格見 `claude_code_brief.md`，視覺設計依 `dashboard-mockup.html`。

目前為**全量人工審核期**：爬蟲與規則引擎只產生「議題＋子分類」建議，所有文章都要先在「待審核」
畫面確認後，才會出現在「日期／議題／趨勢」三個檢視。

## 專案結構

```
newsfetch/            Python 套件
  config.py           關鍵字庫 SEED_TERMS、議題規則 TOPICS、子分類規則 SUBCATEGORIES（擴充關鍵字改這裡）
  classifier.py       規則式分類（純字串比對，不呼叫 LLM）
  extract.py          單篇文章解析（每日爬蟲與手動新增共用）
  sources/ctee.py     工商時報搜尋頁
  sources/udn.py      經濟日報：搜尋頁 → udn 搜尋 API → RSS 三段式備援
  crawler.py          每日爬蟲流程
  review.py           待審核：寫入佇列、核准、刪除、手動新增
  stats.py            分類準確率（議題＋子分類組合）／爬蟲涵蓋率（文章）
  llm_reports.py      月度重點報告、趨勢報告（Claude API）
  export.py           輸出前端 JSON
run_daily.py          每日排程入口
apply_review.py       批次套用審核結果（GitHub Pages 模式）
generate_reports.py   月度／趨勢報告
serve.py              本地審核伺服器
docs/                 前端（GitHub Pages 從這裡部署）；docs/data/*.json 由程式產生
data/news.db          SQLite 資料庫
logs/                 每日執行報告 YYYY-MM-DD-report.md／.json
```

## 第一次設定

1. **GitHub Pages**：Settings → Pages → Source 選「Deploy from a branch」，分支選 `main`、資料夾選 `/docs`。
2. **Actions 寫入權限**：Settings → Actions → General → Workflow permissions 選「Read and write permissions」
   （workflow 需要把資料庫與報告 commit 回 repo）。
3. **Claude API 金鑰**（月度／趨勢報告用）：Settings → Secrets and variables → Actions 新增 `ANTHROPIC_API_KEY`。
   預設模型為 `claude-opus-5`，可用環境變數 `NEWSFETCH_CLAUDE_MODEL` 更換。
4. **審核用 Token**（在 GitHub Pages 上審核才需要）：建立 fine-grained personal access token，
   只授權這個 repo，權限 `Actions: Read and write`。第一次在「待審核」畫面送出時會要求填入，
   只存在該瀏覽器的 localStorage。

## 排程（GitHub Actions）

| Workflow | 觸發 | 內容 |
|---|---|---|
| `daily-crawl.yml` | 每天台灣時間 07:00，也可手動執行（可只跑指定關鍵字） | 爬蟲 → 待審核佇列 → 前端 JSON → 執行報告 |
| `review-apply.yml` | 儀表板按「送出」 | 套用審核結果（核准／刪除／手動新增） |
| `reports.yml` | 每月 1 日（月度）、1/4/7/10 月 2 日（趨勢），也可手動執行 | 月度重點報告、趨勢報告；手動執行可指定單一月份／議題重新生成 |

三個 workflow 共用同一個 concurrency group，依序寫入資料庫，不會互相衝突。
GitHub 的 cron 可能延遲數分鐘到數十分鐘，屬正常現象；爬蟲預設回溯 2 天（`NEWSFETCH_LOOKBACK_DAYS`）以容忍延遲。

## 審核的兩種方式

- **GitHub Pages（線上）**：審核結果先暫存在瀏覽器，按「送出」後觸發 `review-apply.yml`，
  處理完成、Pages 重新部署後（通常數分鐘）網站即更新。手動新增的連結也在 workflow 中抓取，
  抓取失敗的原因會顯示在該次 workflow 的輸出與 `logs/review-*.log`。
- **本地（即時）**：`python serve.py` 後開 http://127.0.0.1:8000 ，審核結果立即寫入 `data/news.db`，
  之後自行 commit／push。

審核規則：每組「議題＋子分類」可個別核准（✓）或移除（✕），可補充議題；所有組合都處理完後自動收錄。
「全部採用」一次核准所有尚未處理的組合；「刪除」需二次確認，為軟刪除並記錄原因。
準確率以伺服器端比對規則建議計算：原樣核准才算正確，改過子分類、補充的議題都算錯誤，被移除的建議
由 suggestions 與 final 的差異推導，整篇刪除不計入準確率。

## 常用指令

```bash
pip install -r requirements.txt
python run_daily.py                       # 完整爬一次
python run_daily.py --terms TISA 亞資中心  # 只跑指定關鍵字（除錯用）
python run_daily.py --export-only         # 只重新輸出前端 JSON
python serve.py                           # 本地審核
python generate_reports.py monthly --month 202609 --topic 信任金融   # 重新生成單一月份／議題
python generate_reports.py trend --dry-run                          # 只看送給 Claude 的內容
python -m pytest                          # 測試
```

## 除錯流程

每次排程後查看 `logs/YYYY-MM-DD-report.md`：各來源／關鍵字成功與失敗筆數、失敗原因分類
（HTTP 錯誤、反爬蟲擋下、逾時、頁面結構改變、欄位為空）、新增待審核清單、規則未命中清單，
以及「需要人工檢視」的警示（例如某來源連續失敗、所有搜尋都沒有連結、多篇解析欄位為空）。
把報告貼給 Claude，依「問題現象／可能原因／改進建議」討論後調整腳本。

## 已知狀況與待確認事項

- **經濟日報**：已用真實網站驗證搜尋頁、udn 搜尋 API 與單篇解析皆可運作。搜尋頁只取搜尋結果區塊
  （`.story__content`），避免抓到頁首跑馬燈的熱門新聞。
- **工商時報**：開發環境連線 ctee.com.tw 回傳 HTTP 403，無法用真實頁面驗證，解析邏輯以通用的
  meta／JSON-LD 結構撰寫並用範例 HTML 測試。第一次在 GitHub Actions 執行後請看執行報告：
  若同樣 403，會歸類為「反爬蟲擋下」，需要再討論替代抓取方式；若搜尋結果混入無關文章，
  請調整 `sources/ctee.py` 的 `SEARCH_CONTAINERS`。
- 同一篇文章在不同議題下的子分類，採「議題關鍵字所在句子」判斷，判斷不出時退回整篇判斷。
- 切換自動分類：`topic_review_mode` 表已就緒（預設全部 `manual_review`），把某議題改為 `auto` 後，
  僅命中自動模式議題且子分類都有判定的文章會直接收錄；介面上的開關尚未設計。

## 與需求文件的差異

- 資料表另外新增：`published_time`（清單顯示時間）、`pending_review.delete_reason`（刪除原因）、
  `crawl_seen`（記錄已看過但超出日期範圍／抓取失敗的網址，避免每天重抓）。
- 「個別修改」按鈕會讓每一組建議都出現子分類下拉選單；子分類未命中的組合則一律直接顯示下拉選單。
- 刪除的二次確認列中多了一個「刪除原因」下拉選單（需求提到要記錄刪除原因）。
