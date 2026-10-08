# 新聞觀測站：台灣金融政策新聞儀表板

每日爬取工商時報、經濟日報，追蹤金管會「金融卓越發展計畫」六大議題；文章經人工審核後才上架。
規格與規則見 `claude_code_brief.md`；本文件只說明設定與操作。

## 專案結構
| 路徑 | 用途 |
|---|---|
| `newsfetch/config.py` | 基礎詞庫（搜尋關鍵字、議題規則、子分類規則） |
| `newsfetch/rules.py` | 合併基礎詞庫與已學習的關鍵字 |
| `newsfetch/classifier.py` | 規則式分類 |
| `newsfetch/extract.py` | 單篇文章解析 |
| `newsfetch/sources/` | 各來源搜尋：`ctee.py`、`udn.py`、`bing.py` |
| `newsfetch/crawler.py` | 每日爬蟲流程 |
| `newsfetch/review.py` | 待審核、核准、刪除、手動新增 |
| `newsfetch/stats.py` | 準確率、涵蓋率 |
| `newsfetch/keyword_learning.py` | 關鍵字學習建議 |
| `newsfetch/llm_reports.py` | 月度／趨勢報告（Claude API） |
| `newsfetch/export.py` | 輸出前端 JSON |
| `newsfetch/notify.py` | 每日通知 |
| `run_daily.py` / `apply_review.py` / `generate_reports.py` / `notify.py` / `serve.py` | 執行入口（見「常用指令」） |
| `docs/` | 前端（GitHub Pages）；`docs/data/*.json` 由程式產生 |
| `data/news.db` | SQLite 資料庫 |
| `logs/` | 每日執行報告 |

## 第一次設定（GitHub 網頁）
1. **Actions 寫入權限**：Settings → Actions → General → Workflow permissions →「Read and write permissions」。
2. **GitHub Pages**：Settings → Pages → Deploy from a branch → `main`、`/docs`。
3. **Claude API 金鑰**（月度／趨勢報告）：Settings → Secrets and variables → Actions → 新增 `ANTHROPIC_API_KEY`。
   - 模型預設 `claude-opus-5`，可用環境變數 `NEWSFETCH_CLAUDE_MODEL` 更換。
4. **審核用 Token**（只有在 GitHub Pages 上審核才需要）：建立 fine-grained token，只授權本 repo，權限 `Actions: Read and write`；
   首次送出審核時填入，只存在該瀏覽器。

## 排程
| Workflow | 時間（台灣） | 內容 |
|---|---|---|
| `daily-crawl.yml` | 每天 08:00；可手動執行並指定關鍵字 | 爬蟲、報告、通知 |
| `review-apply.yml` | 儀表板送出時 | 套用審核結果 |
| `reports.yml` | 每月 1 日、1/4/7/10 月 2 日；可手動指定月份／議題 | 月度／趨勢報告 |

- 改時間：修改 workflow 的 `cron`（UTC＝台灣時間減 8 小時）。
- GitHub 排程可能延遲數分鐘到數十分鐘；爬蟲回溯 2 天，不會漏抓。
- 公開 repo 連續 60 天無活動時排程會被停用，需到 Actions 頁面重新啟用。

## 通知
- 每日爬蟲完成後在「每日爬蟲通知」Issue 留言摘要並 @ repo 擁有者，GitHub 會寄 Email；失敗時留言失敗通知。
- 這則 Issue 請保持開啟；關閉後下次執行會自動再開一則。
- 收不到信：GitHub 頭像 → Settings → Notifications，勾選「Participating, @mentions and custom」的 Email。
- 改 @ 對象：設定環境變數 `NOTIFY_MENTION`。

## 審核
- **線上（GitHub Pages）**：審核結果暫存在瀏覽器，按「送出」後由 `review-apply.yml` 寫入，數分鐘後網站更新；
  手動新增的抓取錯誤記於該次 workflow 輸出與 `logs/review-*.log`。
- **本機**：`python serve.py` → http://127.0.0.1:8000，即時寫入 `data/news.db`，之後自行 commit／push。
- 關鍵字學習：在待審核畫面底部「關鍵字學習」採用或忽略；門檻在 `keyword_learning.py` 開頭調整。

## 常用指令
```bash
pip install -r requirements.txt
python run_daily.py                        # 完整爬一次
python run_daily.py --terms TISA 亞資中心   # 只跑指定關鍵字
python run_daily.py --export-only          # 只重新輸出前端 JSON
python serve.py                            # 本機審核
python generate_reports.py monthly --month 202609 --topic 信任金融   # 重新生成單一月份／議題
python generate_reports.py trend --dry-run # 只預覽送給 Claude 的內容
python -m pytest                           # 測試
```

## 除錯
1. 查看 `logs/YYYY-MM-DD-report.md`，先看「需要人工檢視」與「失敗原因分類」。
2. 將報告貼給 Claude，依「問題現象／可能原因／改進建議」討論後調整。
