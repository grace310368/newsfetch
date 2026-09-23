/* 新聞觀測站前端：純靜態，讀取 data/*.json。
 * 審核操作兩種模式：
 *  - 本地模式（python serve.py）：直接呼叫 /api/*，即時寫入 SQLite
 *  - GitHub Pages 模式：審核結果暫存在瀏覽器，按「送出」後以 workflow_dispatch 觸發 review-apply workflow
 */
(() => {
  'use strict';

  const TOPICS_DEFAULT = ['亞洲資產管理中心', '國際級資本市場', '三軌金融', '全齡金融', '信任金融', '金融大回饋'];
  const SUBCATS_DEFAULT = ['政策與法規', '商品與業務', '同業動態'];
  const DOW = ['日', '一', '二', '三', '四', '五', '六'];
  const DELETE_REASONS = ['關鍵字誤觸，與議題無關', '重複報導', '非新聞內容（廣告、公告等）', '其他'];
  const LS = { view: 'nf-view', topic: 'nf-topic', queue: 'nf-queue', submitted: 'nf-submitted', gh: 'nf-github' };

  const ICON = {
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    cross: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="6" y1="18" x2="18" y2="6"/></svg>',
    undo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 14l-4 -4l4 -4"/><path d="M5 10h11a4 4 0 1 1 0 8h-1"/></svg>',
    external: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1 -2 2H5a2 2 0 0 1 -2 -2V8a2 2 0 0 1 2 -2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>',
    trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="7" x2="20" y2="7"/><path d="M6 7l1 13a2 2 0 0 0 2 2h6a2 2 0 0 0 2 -2l1 -13"/><path d="M10 11l0 6"/><path d="M14 11l0 6"/><path d="M9 7l0 -2a1 1 0 0 1 1 -1h4a1 1 0 0 1 1 1l0 2"/></svg>',
    arrow: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="13 6 19 12 13 18"/></svg>',
    chevron: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>',
    tag: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4h-5.5a1.5 1.5 0 0 0 -1.5 1.5v5.5c0 .4 .15 .78 .44 1.06l8 8c.58 .58 1.53 .58 2.12 0l6-6c.58 -.58 .58 -1.53 0 -2.12l-8 -8c-.28 -.28 -.66 -.44 -1.06 -.44z"/><circle cx="9" cy="9" r="1"/></svg>',
  };

  // ------------------------------------------------------------------ utils
  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pad = (n) => String(n).padStart(2, '0');
  const ymd = (y, m, d) => `${y}-${pad(m)}-${pad(d)}`;
  const mmdd = (date) => (date ? `${date.slice(5, 7)}.${date.slice(8, 10)}` : '');
  const store = {
    get(key, fallback) {
      try { const v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); } catch { return fallback; }
    },
    set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* 私密模式等情況忽略 */ } },
  };
  function taipeiToday() {
    const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
    return parts; // YYYY-MM-DD
  }
  let toastTimer;
  function toast(msg) {
    const el = $('#toast');
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 3200);
  }

  // ------------------------------------------------------------------ state
  const state = {
    view: 'date',
    mode: 'pages', // 'local' | 'pages'
    data: { articles: [], pending: [], reports: { monthly: {}, trend: {} }, stats: null, meta: null },
    topics: TOPICS_DEFAULT,
    subcats: SUBCATS_DEFAULT,
    today: taipeiToday(),
    // 日期檢視
    cal: { year: 0, month: 0, selected: null, query: '', scope: 'all' },
    // 議題／趨勢
    topic: TOPICS_DEFAULT[0],
    topicMonth: null, // 'YYYY-MM'
    monthInput: '',
    monthError: '',
    subFilter: '全部',
    // 待審核
    cards: {}, // id -> 卡片狀態
    manual: { url: '', topics: [], open: false, busy: false, msg: '', error: false },
    statsOpen: false,
    queue: store.get(LS.queue, []),
    submitted: store.get(LS.submitted, []),
    gh: store.get(LS.gh, {}),
    syncOpen: false,
    syncBusy: false,
    syncMsg: '',
  };

  const topicIndex = (t) => Math.max(0, state.topics.indexOf(t)) + 1;
  const topicTag = (t) => `<span class="tag t${topicIndex(t)}">${esc(t)}</span>`;

  // ------------------------------------------------------------------ data
  async function fetchJSON(name, fallback) {
    try {
      const res = await fetch(`data/${name}.json?t=${Date.now()}`, { cache: 'no-store' });
      if (!res.ok) return fallback;
      return await res.json();
    } catch { return fallback; }
  }

  async function loadData() {
    const [articles, pending, reports, stats, meta] = await Promise.all([
      fetchJSON('articles', []), fetchJSON('pending', []),
      fetchJSON('reports', { monthly: {}, trend: {} }), fetchJSON('stats', null), fetchJSON('meta', null),
    ]);
    state.data = { articles, pending, reports, stats, meta };
    if (meta?.topics?.length) state.topics = meta.topics;
    if (meta?.subcategories?.length) state.subcats = meta.subcategories;
    if (!state.topics.includes(state.topic)) state.topic = state.topics[0];
    pruneSubmitted();
    syncCards();
  }

  async function detectMode() {
    try {
      const res = await fetch('api/health', { cache: 'no-store' });
      if (res.ok && (await res.json()).mode === 'local') return 'local';
    } catch { /* 靜態部署 */ }
    return 'pages';
  }

  // 已送出到 GitHub 但資料尚未更新的文章先隱藏；資料產生時間晚於送出時間即視為已同步
  function pruneSubmitted() {
    const gen = state.data.meta?.generated_at ? Date.parse(state.data.meta.generated_at.replace(/([+-]\d{2})(\d{2})$/, '$1:$2')) : 0;
    state.submitted = state.submitted.filter((s) => !(gen && gen > s.at + 5000));
    store.set(LS.submitted, state.submitted);
  }

  function hiddenPendingIds() {
    const ids = new Set();
    state.queue.forEach((op) => op.id != null && ids.add(op.id));
    state.submitted.forEach((s) => s.ids.forEach((id) => ids.add(id)));
    return ids;
  }

  function visiblePending() {
    const hidden = hiddenPendingIds();
    return state.data.pending.filter((p) => !hidden.has(p.id));
  }

  function syncCards() {
    const next = {};
    for (const p of state.data.pending) {
      next[p.id] = state.cards[p.id] || {
        items: p.suggestions.map((s) => ({
          topic: s.topic, sub: s.subcategory, orig: s.subcategory, reason: s.reason, suggested: true, state: 'pending',
        })),
        edit: false, confirm: false, reason: DELETE_REASONS[0], addTopic: '', msg: '', busy: false,
      };
    }
    state.cards = next;
  }

  // ------------------------------------------------------------------ render: shell
  function render() {
    document.querySelectorAll('.nav-item').forEach((el) => el.classList.toggle('active', el.dataset.view === state.view));
    $('#search-bar').hidden = state.view !== 'date';
    $('#header').classList.toggle('compact', state.view !== 'date');
    const badge = $('#nav-badge');
    const n = visiblePending().length;
    badge.hidden = n === 0;
    badge.textContent = n > 99 ? '99+' : n;
    const view = $('#view');
    const html = { date: renderDate, topic: renderTopic, trend: renderTrend, review: renderReview }[state.view]();
    view.innerHTML = html;
    if (state.view === 'topic' || state.view === 'trend') {
      const active = view.querySelector('.topic-tab.active');
      if (active) active.scrollIntoView({ block: 'nearest', inline: 'center' });
    }
  }

  // ------------------------------------------------------------------ render: 日期
  function articleMatches(a, q) {
    if (!q) return true;
    const hay = [a.title, a.summary, a.keywords, a.source, ...(a.classifications || []).map((c) => `${c.topic} ${c.subcategory || ''}`)].join(' ').toLowerCase();
    return q.toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w));
  }

  function newsItemDate(a, showDate) {
    const tags = (a.classifications || []).map((c) => topicTag(c.topic)).join('');
    const when = [showDate ? mmdd(a.date) : '', a.time || ''].filter(Boolean).join(' ');
    return `<div class="news-item">
      <div class="news-meta">${tags}<span class="news-source">${esc(a.source)}</span></div>
      <a class="news-title" href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">${esc(a.title)}</a>
      ${when ? `<span class="news-time">${esc(when)}</span>` : ''}
    </div>`;
  }

  function renderDate() {
    const { cal } = state;
    const q = cal.query.trim();
    const matches = state.data.articles.filter((a) => articleMatches(a, q));
    const byDate = {};
    matches.forEach((a) => { (byDate[a.date] ||= []).push(a); });

    const first = new Date(cal.year, cal.month - 1, 1);
    const daysInMonth = new Date(cal.year, cal.month, 0).getDate();
    const prevDays = new Date(cal.year, cal.month - 1, 0).getDate();
    const lead = first.getDay();
    const cells = [];
    for (let i = lead - 1; i >= 0; i--) {
      const d = prevDays - i;
      const [py, pm] = cal.month === 1 ? [cal.year - 1, 12] : [cal.year, cal.month - 1];
      cells.push({ date: ymd(py, pm, d), d, dim: true });
    }
    for (let d = 1; d <= daysInMonth; d++) cells.push({ date: ymd(cal.year, cal.month, d), d, dim: false });
    let nd = 1;
    while (cells.length % 7) {
      const [ny, nm] = cal.month === 12 ? [cal.year + 1, 1] : [cal.year, cal.month + 1];
      cells.push({ date: ymd(ny, nm, nd), d: nd++, dim: true });
    }

    const grid = DOW.map((d) => `<div class="cal-dow">${d}</div>`).join('') + cells.map((c) => {
      const cls = ['cal-day', c.dim && 'dim', byDate[c.date] && 'has-news', c.date === state.today && 'today',
        c.date === cal.selected && (!q || cal.scope === 'day') && 'selected'].filter(Boolean).join(' ');
      const count = byDate[c.date]?.length || 0;
      return `<button class="${cls}" data-action="pick-day" data-date="${c.date}" aria-label="${c.date}${count ? `，${count} 則新聞` : ''}"><span class="num">${c.d}</span><span class="dot"></span></button>`;
    }).join('');

    let label; let list;
    if (q && cal.scope === 'all') {
      label = `搜尋「<b>${esc(q)}</b>」　共 ${matches.length} 則相關新聞`;
      list = matches.length ? matches.map((a) => newsItemDate(a, true)).join('') : '<div class="empty">找不到符合的新聞，試試其他關鍵字。</div>';
    } else {
      const sel = cal.selected;
      const items = byDate[sel] || [];
      const d = new Date(`${sel}T00:00:00`);
      label = `<b>${d.getMonth() + 1}月${d.getDate()}日（${DOW[d.getDay()]}）</b>　共 ${items.length} 則相關新聞`;
      if (q) label += `<button class="link-btn" data-action="search-all">顯示全部搜尋結果</button>`;
      list = items.length ? items.map((a) => newsItemDate(a, false)).join('')
        : `<div class="empty">${q ? '這一天沒有符合搜尋的新聞。' : '這一天沒有相關新聞。'}</div>`;
    }

    return `<div class="cal-nav">
        <button class="cal-arrow" data-action="cal-prev" aria-label="上個月">‹</button>
        <span class="cal-month">${cal.year}年${cal.month}月</span>
        <button class="cal-arrow" data-action="cal-next" aria-label="下個月">›</button>
      </div>
      <div class="cal-grid">${grid}</div>
      <div class="selected-date-label">${label}</div>
      ${list}`;
  }

  // ------------------------------------------------------------------ render: 議題
  function topicTabs() {
    return `<div class="topic-tabs" role="tablist">${state.topics.map((t) =>
      `<button class="topic-tab${t === state.topic ? ' active' : ''}" role="tab" aria-selected="${t === state.topic}" data-action="topic" data-topic="${esc(t)}">${esc(t)}</button>`).join('')}</div>`;
  }

  function topicArticles(topic) {
    return state.data.articles.filter((a) => a.classifications.some((c) => c.topic === topic));
  }

  function defaultTopicMonth(topic) {
    const arts = topicArticles(topic);
    return arts.length ? arts[0].date.slice(0, 7) : state.today.slice(0, 7);
  }

  function renderTopic() {
    const topic = state.topic;
    const month = state.topicMonth || defaultTopicMonth(topic);
    const [y, m] = month.split('-').map(Number);
    const arts = topicArticles(topic).filter((a) => a.date.startsWith(month));
    const report = state.data.reports.monthly?.[topic]?.[month];

    let body;
    if (!arts.length && !report) {
      body = '<div class="month-report"><p class="muted">本月無相關新聞</p></div>';
    } else {
      const reportHtml = report
        ? state.subcats.map((s) => `<div class="subreport"><p class="rlabel">${esc(s)}</p><p>${esc(report[s] || '本月無相關新聞')}</p></div>`).join('')
        : `<p class="muted">${month === state.today.slice(0, 7) ? '本月重點報告將於下個月初自動生成。' : '本月重點報告尚未生成。'}</p>`;
      const withSub = arts.map((a) => ({ a, sub: a.classifications.find((c) => c.topic === topic)?.subcategory }));
      const filtered = state.subFilter === '全部' ? withSub : withSub.filter((x) => x.sub === state.subFilter);
      const chips = ['全部', ...state.subcats].map((s) =>
        `<button class="subcat-chip${s === state.subFilter ? ' active' : ''}" data-action="subfilter" data-sub="${esc(s)}">${esc(s)}</button>`).join('');
      const items = filtered.map(({ a, sub }) => {
        const others = a.classifications.filter((c) => c.topic !== topic).map((c) => c.topic);
        return `<div class="news-item">
          <div class="news-meta">
            ${sub ? `<span class="subcat-label">${esc(sub)}</span>` : ''}
            <span class="news-source">${esc(a.source)}</span><span class="news-dot">·</span><span class="news-source">${mmdd(a.date)}</span>
            ${others.length ? `<span class="cross-topic-tag">${ICON.tag}同時歸類於${esc(others.join('、'))}</span>` : ''}
          </div>
          <a class="news-title" href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">${esc(a.title)}</a>
        </div>`;
      }).join('');
      body = `<div class="month-report">${reportHtml}</div>
        <div class="month-count">本月共 ${arts.length} 則相關新聞</div>
        ${arts.length ? `<div class="subcat-filter">${chips}</div>
        ${items || `<div class="empty">本月此子分類無相關新聞。</div>`}` : '<div class="empty">本月無相關新聞</div>'}`;
    }

    return `${topicTabs()}
      <div class="month-picker">
        <div class="month-input-wrap">
          <input id="month-input" type="text" placeholder="YYYYMM" maxlength="6" inputmode="numeric" value="${esc(state.monthInput)}" aria-label="輸入年月，例如 202609">
          <button class="go" data-action="month-go" aria-label="跳至該月">${ICON.arrow}</button>
        </div>
        ${state.monthError ? `<div class="month-error">${esc(state.monthError)}</div>` : ''}
      </div>
      <p class="month-title">${y}年${m}月</p>
      ${body}`;
  }

  // ------------------------------------------------------------------ render: 趨勢
  function renderTrend() {
    const topic = state.topic;
    const stages = state.data.reports.trend?.[topic] || [];
    const months = Object.keys(state.data.reports.monthly?.[topic] || {}).sort();
    const since = months.length ? `${months[0].replace('-', '.')} 至今` : '';
    const list = stages.length ? stages.map((s, i) => `<div class="news-item">
        <div class="news-meta">
          <span class="tag t${topicIndex(topic)}" style="opacity:.85">${esc(s.period)}${i === 0 ? '（最新）' : ''}</span>
          ${s.subcategory ? `<span class="subcat-label">${esc(s.subcategory)}</span>` : ''}
        </div>
        <p class="stage-text">${esc(s.description)}</p>
      </div>`).join('')
      : `<div class="empty">此議題尚未累積足夠的月度重點報告（目前 ${months.length} 份），趨勢洞察會在累積數個月後生成。</div>`;
    return `${topicTabs()}
      <div class="section-label" style="margin-top:16px;">趨勢洞察${since ? `（${since}）` : ''}</div>
      ${list}
      <div class="review-block">
        <p class="review-title">洞察說明</p>
        <p class="body">此報告由每月重點摘要彙整生成，建議每季更新一次，用以掌握議題討論方向的中長期變化，而非單月的個別事件。</p>
      </div>`;
  }

  // ------------------------------------------------------------------ render: 待審核
  function subSelect(id, idx, value) {
    return `<select class="ts-sub-select" data-action="set-sub" data-id="${id}" data-idx="${idx}" aria-label="指定子分類">
      <option value="">選擇子分類</option>
      ${state.subcats.map((s) => `<option${s === value ? ' selected' : ''}>${esc(s)}</option>`).join('')}
    </select>`;
  }

  function renderRow(id, card, it, idx) {
    const editable = it.state === 'pending' && (card.edit || !it.orig || !it.suggested);
    let sub;
    if (editable) sub = subSelect(id, idx, it.sub);
    else if (it.sub) sub = `<span class="ts-sub">${esc(it.sub)}</span>`;
    else sub = '<span class="ts-sub none">子分類無命中，需人工指定</span>';
    const stateLabel = it.state === 'approved' ? '<span class="ts-state">已核准</span>'
      : it.state === 'removed' ? '<span class="ts-state">已移除</span>' : '';
    const reason = it.suggested ? (it.reason || '') : '人工補充議題';
    const actions = it.state === 'pending'
      ? `<button class="ts-accept" data-action="accept" data-id="${id}" data-idx="${idx}" aria-label="核准此議題">${ICON.check}</button>
         <button class="ts-remove" data-action="remove" data-id="${id}" data-idx="${idx}" aria-label="移除此議題">${ICON.cross}</button>`
      : `<button class="ts-undo" data-action="undo" data-id="${id}" data-idx="${idx}" aria-label="復原">${ICON.undo}</button>`;
    return `<div class="topic-suggest-row ${it.state}">
      <div class="ts-info">
        <span class="ts-topic">${esc(it.topic)}</span>
        ${sub}${stateLabel}
        ${reason ? `<span class="ts-reason">${esc(reason)}</span>` : ''}
      </div>
      <div class="ts-actions">${actions}</div>
    </div>`;
  }

  function renderCard(p) {
    const card = state.cards[p.id];
    const used = new Set(card.items.map((i) => i.topic));
    const addable = state.topics.filter((t) => !used.has(t));
    const hasItems = card.items.length > 0;
    const addRow = addable.length ? `<div class="add-topic-row">
        <span>${hasItems ? '補充議題：' : '指定議題：'}</span>
        <select data-action="add-topic-select" data-id="${p.id}" aria-label="選擇議題">
          <option value="">選擇議題</option>
          ${addable.map((t) => `<option${t === card.addTopic ? ' selected' : ''}>${esc(t)}</option>`).join('')}
        </select>
        <button class="add-btn" data-action="add-topic" data-id="${p.id}">＋ 新增</button>
      </div>` : '';
    const rows = hasItems ? card.items.map((it, idx) => renderRow(p.id, card, it, idx)).join('')
      : '<p class="ts-empty">規則無命中任何議題，需人工判斷分類</p>';
    const actions = card.confirm
      ? `<div class="confirm-delete">
          <span class="cd-text">確定要刪除這則新聞嗎？此動作無法復原。
            <select class="cd-reason" data-action="delete-reason" data-id="${p.id}" aria-label="刪除原因">
              ${DELETE_REASONS.map((r) => `<option${r === card.reason ? ' selected' : ''}>${esc(r)}</option>`).join('')}
            </select>
          </span>
          <div class="cd-btns">
            <button class="cd-no" data-action="delete-cancel" data-id="${p.id}">取消</button>
            <button class="cd-yes" data-action="delete-confirm" data-id="${p.id}"${card.busy ? ' disabled' : ''}>確定刪除</button>
          </div>
        </div>`
      : `<div class="review-actions">
          <button class="approve" data-action="approve-all" data-id="${p.id}"${card.busy ? ' disabled' : ''}>全部採用</button>
          <button class="edit${card.edit ? ' on' : ''}" data-action="toggle-edit" data-id="${p.id}">${card.edit ? '完成修改' : '個別修改'}</button>
          <button class="delete" data-action="delete" data-id="${p.id}" aria-label="刪除這則新聞">${ICON.trash}</button>
        </div>`;
    const when = [mmdd(p.date), p.time].filter(Boolean).join(' ');
    return `<div class="review-card" id="card-${p.id}">
      <a class="rt" href="${esc(p.url)}" target="_blank" rel="noopener noreferrer"><span>${esc(p.title)}</span>${ICON.external}</a>
      <span class="src">${esc(p.source)}・${esc(when || '日期不明')}${p.origin === 'manual' ? '<span class="origin-tag">手動新增</span>' : ''}</span>
      <div class="topic-suggest-list">${rows}${addRow}</div>
      ${card.msg ? `<p class="card-msg">${esc(card.msg)}</p>` : ''}
      ${actions}
    </div>`;
  }

  function renderManualAdd() {
    const m = state.manual;
    const label = m.topics.length ? m.topics.join('、') : '選擇議題（可複選）';
    return `<div class="manual-add">
      <p class="ma-label">手動新增新聞</p>
      <input class="ma-url-input" id="ma-url" type="url" placeholder="貼上新聞連結，如 https://www.ctee.com.tw/news/..." value="${esc(m.url)}" autocomplete="off">
      <div class="ma-row">
        <div class="ma-topic-select">
          <button class="ma-topic-toggle${m.topics.length ? ' has-value' : ''}" data-action="ma-toggle" aria-expanded="${m.open}">${esc(label)}${ICON.chevron}</button>
          <div class="ma-topic-panel"${m.open ? '' : ' hidden'}>
            ${state.topics.map((t) => `<label class="ma-topic-option"><input type="checkbox" data-action="ma-topic" value="${esc(t)}"${m.topics.includes(t) ? ' checked' : ''}>${esc(t)}</label>`).join('')}
          </div>
        </div>
        <button class="ma-submit" data-action="ma-submit"${m.busy ? ' disabled' : ''}>${m.busy ? '抓取中…' : '新增'}</button>
      </div>
      ${m.msg ? `<p class="form-msg${m.error ? ' error' : ''}">${esc(m.msg)}</p>` : ''}
    </div>`;
  }

  function renderSyncCard() {
    if (state.mode !== 'pages') return '';
    const n = state.queue.length;
    const pendingSubmit = state.submitted.reduce((s, x) => s + x.count, 0);
    if (!n && !pendingSubmit && !state.syncOpen) return '';
    const gh = state.gh;
    return `<div class="sync-card">
      <p class="ma-label">審核結果同步</p>
      <div class="sync-row">
        <span>${n ? `有 <b>${n}</b> 筆審核結果尚未送出` : pendingSubmit ? `已送出 ${pendingSubmit} 筆，等待資料更新（約數分鐘）` : '尚無待送出的審核結果'}</span>
        ${n ? `<button class="ma-submit" data-action="sync-submit"${state.syncBusy ? ' disabled' : ''}>${state.syncBusy ? '送出中…' : '送出'}</button>` : ''}
      </div>
      <div class="sync-settings"${state.syncOpen ? '' : ' hidden'}>
        <input class="ma-url-input" id="gh-repo" placeholder="GitHub 儲存庫，如 owner/newsfetch" value="${esc(gh.repo || guessRepo())}">
        <input class="ma-url-input" id="gh-ref" placeholder="分支（預設 main）" value="${esc(gh.ref || '')}">
        <input class="ma-url-input" id="gh-token" type="password" placeholder="GitHub Token（需 Actions 寫入權限）" value="${esc(gh.token || '')}" autocomplete="off">
        <button class="link-btn" data-action="sync-save">儲存設定</button>
        <p class="sync-note">Token 只存在這台裝置的瀏覽器，不會上傳。送出後由 GitHub Actions 寫入資料庫並更新網站。</p>
      </div>
      ${state.syncMsg ? `<p class="form-msg error">${esc(state.syncMsg)}</p>` : ''}
      ${state.syncOpen ? '' : '<p class="sync-note"><button class="link-btn" data-action="sync-settings">同步設定</button></p>'}
    </div>`;
  }

  function renderStats() {
    const st = state.data.stats;
    const acc = st?.accuracy;
    const cov = st?.coverage;
    const rows = state.topics.map((t) => {
      const r = acc?.topics?.find((x) => x.topic === t);
      const pct = r && r.rate != null ? Math.round(r.rate * 100) : null;
      return `<div class="accuracy-row">
        <span class="topic-name">${esc(t)}</span>
        <span class="accuracy-bar-track"><span class="accuracy-bar-fill" style="width:${pct ?? 0}%"></span></span>
        <span class="accuracy-pct${pct == null ? ' na' : ''}" title="${r ? `${r.correct}/${r.total} 組` : ''}">${pct == null ? '—' : `${pct}%`}</span>
      </div>`;
    }).join('');
    const covRate = cov?.rate != null ? `${(cov.rate * 100).toFixed(1)}%` : '—';
    const autoTopics = Object.entries(state.data.meta?.topic_modes || {}).filter(([, m]) => m === 'auto').map(([t]) => t);
    return `<div class="stats-area">
      <div class="review-mode-banner">
        <div class="banner-top">
          <span>${autoTopics.length ? `「${esc(autoTopics.join('、'))}」已切換為自動分類，其餘議題仍為<b>人工審核</b>。` : '目前為<b>全量人工審核期</b>，規則建議僅供參考，尚未自動上架。'}</span>
          <button class="banner-toggle${state.statsOpen ? ' open' : ''}" data-action="stats-toggle" aria-expanded="${state.statsOpen}">準確率統計${ICON.chevron}</button>
        </div>
        <div class="accuracy-detail"${state.statsOpen ? '' : ' hidden'}>
          ${rows}
          <p class="accuracy-note">準確率＝人工審核時「採用規則建議」的比例（近30天，以「議題＋子分類」組合計算）。建議單一議題連續穩定達 90% 以上時，可考慮切換該議題為自動分類。${acc ? `近30天另有 ${acc.removed_suggestions} 組建議被移除、${acc.deleted_articles} 則文章整篇刪除（規則誤觸參考，不計入準確率）。` : ''}</p>
        </div>
      </div>
      <div class="coverage-block"${state.statsOpen ? '' : ' hidden'}>
        <p class="cv-label">爬蟲涵蓋率</p>
        <div class="cv-stat-row"><span class="cv-name">近30天自動爬取</span><span class="cv-value">${cov?.crawler ?? 0} 則</span></div>
        <div class="cv-stat-row"><span class="cv-name">手動新增（爬蟲漏抓）</span><span class="cv-value"><em>${cov?.manual ?? 0} 則</em></span></div>
        <div class="cv-stat-row"><span class="cv-name">涵蓋率</span><span class="cv-value"><em>${covRate}</em></span></div>
        <p class="cv-note">涵蓋率＝自動爬取則數 ÷（自動爬取＋手動新增）。手動新增的新聞代表爬蟲漏抓，數量偏高時應檢視關鍵字庫或該來源網站的抓取邏輯。</p>
      </div>
    </div>`;
  }

  function renderReview() {
    const list = visiblePending();
    const todayCount = list.filter((p) => (p.created_at || '').startsWith(state.today)).length;
    const cards = list.length ? list.map(renderCard).join('') : '<div class="empty">目前沒有待審核的新聞。</div>';
    return `<div class="section-label" style="margin-top:0;">待審核（本日新增 ${todayCount} 則・共 ${list.length} 則待處理）</div>
      ${renderSyncCard()}
      ${renderManualAdd()}
      ${cards}
      ${renderStats()}`;
  }

  // ------------------------------------------------------------------ 審核邏輯
  function guessRepo() {
    const m = location.hostname.match(/^([^.]+)\.github\.io$/);
    const seg = location.pathname.split('/').filter(Boolean)[0];
    return m && seg ? `${m[1]}/${seg}` : '';
  }

  async function api(path, body) {
    const res = await fetch(`api/${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
    if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  function saveQueue() { store.set(LS.queue, state.queue); }

  async function submitOp(op, card) {
    if (state.mode === 'local') {
      if (card) { card.busy = true; render(); }
      try {
        await api(op.type === 'finalize' ? 'review/finalize' : 'review/delete', op);
        await loadData();
        toast(op.type === 'finalize' ? '已收錄至正式資料' : '已刪除這則新聞');
      } catch (e) {
        if (card) { card.busy = false; card.msg = e.message; }
      }
    } else {
      state.queue.push(op);
      saveQueue();
      toast(op.type === 'finalize' ? '已完成審核，待送出' : '已標記刪除，待送出');
    }
    render();
  }

  // 每一組建議都已核准或移除時，自動完成這篇文章的審核
  function maybeFinalize(id) {
    const card = state.cards[id];
    if (card.items.some((i) => i.state === 'pending')) return;
    const approved = card.items.filter((i) => i.state === 'approved');
    if (!approved.length) {
      card.msg = '所有議題都已移除。若這則新聞與六大議題都無關，請改用刪除；或補充正確的議題。';
      return;
    }
    submitOp({ type: 'finalize', id, items: approved.map((i) => ({ topic: i.topic, subcategory: i.sub })) }, card);
  }

  function acceptItem(card, it) {
    if (!it.sub) {
      card.msg = `請先為「${it.topic}」指定子分類，才能核准。`;
      return false;
    }
    it.state = 'approved';
    return true;
  }

  async function manualSubmit() {
    const m = state.manual;
    m.url = ($('#ma-url')?.value || m.url).trim();
    m.msg = ''; m.error = false;
    if (!m.url) { Object.assign(m, { msg: '請貼上新聞連結。', error: true }); return render(); }
    if (!/^https?:\/\/([a-z0-9-]+\.)*(ctee\.com\.tw|udn\.com)\//i.test(m.url)) {
      Object.assign(m, { msg: '目前只支援工商時報（ctee.com.tw）與經濟日報（udn.com）的新聞連結。', error: true }); return render();
    }
    if (!m.topics.length) { Object.assign(m, { msg: '請至少選擇一個議題。', error: true }); return render(); }
    const norm = (u) => u.replace(/^https?:\/\/(www\.|m\.)?/i, '').replace(/[?#].*$/, '').replace(/\/$/, '').toLowerCase();
    const key = norm(m.url);
    const exists = [...state.data.articles, ...state.data.pending].some((a) => norm(a.url) === key)
      || state.queue.some((op) => op.type === 'manual_add' && norm(op.url) === key);
    if (exists) { Object.assign(m, { msg: '這則新聞已經收錄。', error: true }); return render(); }

    m.open = false;
    if (state.mode === 'local') {
      m.busy = true; render();
      try {
        const res = await api('manual-add', { url: m.url, topics: m.topics });
        await loadData();
        Object.assign(m, { url: '', topics: [], msg: `已加入待審核：${res.title}`, error: false });
      } catch (e) {
        Object.assign(m, { msg: e.message, error: true });
      }
      m.busy = false;
    } else {
      state.queue.push({ type: 'manual_add', url: m.url, topics: [...m.topics] });
      saveQueue();
      Object.assign(m, { url: '', topics: [], msg: '已加入待送出清單。送出後系統會自動抓取標題、日期與摘要，並出現在待審核清單。', error: false });
    }
    render();
  }

  async function syncSubmit() {
    const gh = state.gh;
    const repo = (gh.repo || guessRepo()).trim();
    if (!gh.token || !repo) {
      state.syncOpen = true;
      state.syncMsg = '請先設定 GitHub 儲存庫與 Token。';
      return render();
    }
    state.syncBusy = true; state.syncMsg = ''; render();
    // workflow_dispatch 的 input 有長度上限，過長時分批送出
    const batches = [];
    let cur = [];
    for (const op of state.queue) {
      if (cur.length && JSON.stringify([...cur, op]).length > 60000) { batches.push(cur); cur = []; }
      cur.push(op);
    }
    if (cur.length) batches.push(cur);
    try {
      for (const ops of batches) {
        const res = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/review-apply.yml/dispatches`, {
          method: 'POST',
          headers: { Accept: 'application/vnd.github+json', Authorization: `Bearer ${gh.token}`, 'X-GitHub-Api-Version': '2022-11-28' },
          body: JSON.stringify({ ref: gh.ref || 'main', inputs: { ops: JSON.stringify(ops) } }),
        });
        if (res.status !== 204) {
          const err = await res.json().catch(() => ({}));
          throw new Error(`GitHub 回應 ${res.status}${err.message ? `：${err.message}` : ''}`);
        }
        state.submitted.push({ at: Date.now(), count: ops.length, ids: ops.filter((o) => o.id != null).map((o) => o.id) });
        state.queue = state.queue.slice(ops.length);
        saveQueue();
        store.set(LS.submitted, state.submitted);
      }
      toast('已送出，GitHub Actions 處理完成後網站會自動更新');
    } catch (e) {
      state.syncMsg = `送出失敗：${e.message}`;
      state.syncOpen = true;
    }
    state.syncBusy = false;
    render();
  }

  // ------------------------------------------------------------------ events
  function setView(view) {
    state.view = view;
    store.set(LS.view, view);
    if (location.hash !== `#${view}`) history.replaceState(null, '', `#${view}`);
    render();
    window.scrollTo(0, 0);
  }

  function goMonth() {
    const raw = ($('#month-input')?.value || state.monthInput).trim();
    const m = raw.match(/^(\d{4})(\d{2})$/);
    if (!m || +m[2] < 1 || +m[2] > 12) {
      state.monthError = '請輸入正確的年月，例如 202609';
    } else {
      state.topicMonth = `${m[1]}-${m[2]}`;
      state.monthError = '';
      state.subFilter = '全部';
    }
    render();
  }

  function onClick(e) {
    const el = e.target.closest('[data-action]');
    if (!el || el.tagName === 'SELECT' || (el.tagName === 'INPUT' && el.type !== 'button')) {
      if (state.manual.open && !e.target.closest('.ma-topic-select')) { state.manual.open = false; render(); }
      return;
    }
    const { action } = el.dataset;
    if (state.manual.open && !el.closest('.ma-topic-select')) state.manual.open = false;
    const id = el.dataset.id != null ? Number(el.dataset.id) : null;
    const card = id != null ? state.cards[id] : null;
    const it = card && el.dataset.idx != null ? card.items[Number(el.dataset.idx)] : null;
    if (card) card.msg = '';

    switch (action) {
      case 'nav': return setView(el.dataset.view);
      case 'cal-prev':
      case 'cal-next': {
        const d = action === 'cal-prev' ? -1 : 1;
        let { year, month } = state.cal;
        month += d;
        if (month < 1) { month = 12; year--; } else if (month > 12) { month = 1; year++; }
        Object.assign(state.cal, { year, month });
        return render();
      }
      case 'pick-day': {
        const date = el.dataset.date;
        const [y, m] = date.split('-').map(Number);
        Object.assign(state.cal, { selected: date, year: y, month: m, scope: 'day' });
        return render();
      }
      case 'search-all': state.cal.scope = 'all'; return render();
      case 'topic':
        state.topic = el.dataset.topic;
        store.set(LS.topic, state.topic);
        state.subFilter = '全部';
        state.topicMonth = null; state.monthInput = ''; state.monthError = '';
        return render();
      case 'month-go': return goMonth();
      case 'subfilter': state.subFilter = el.dataset.sub; return render();
      case 'accept':
        if (acceptItem(card, it)) maybeFinalize(id);
        return render();
      case 'remove':
        it.state = 'removed';
        maybeFinalize(id);
        return render();
      case 'undo':
        if (!it.suggested && it.state === 'removed') card.items.splice(Number(el.dataset.idx), 1);
        else it.state = 'pending';
        return render();
      case 'add-topic': {
        const t = card.addTopic;
        if (!t) { card.msg = '請先選擇要補充的議題。'; return render(); }
        const existing = card.items.find((i) => i.topic === t);
        if (existing) existing.state = 'pending';
        else card.items.push({ topic: t, sub: null, orig: null, reason: '', suggested: false, state: 'pending' });
        card.addTopic = '';
        return render();
      }
      case 'approve-all': {
        const pendingItems = card.items.filter((i) => i.state === 'pending');
        if (!card.items.length) { card.msg = '規則無命中任何議題，請先指定議題與子分類。'; return render(); }
        const missing = pendingItems.filter((i) => !i.sub);
        if (missing.length) { card.msg = `請先為「${missing.map((i) => i.topic).join('」「')}」指定子分類。`; return render(); }
        pendingItems.forEach((i) => { i.state = 'approved'; });
        maybeFinalize(id);
        return render();
      }
      case 'toggle-edit': card.edit = !card.edit; return render();
      case 'delete': card.confirm = true; return render();
      case 'delete-cancel': card.confirm = false; return render();
      case 'delete-confirm':
        card.confirm = false;
        return submitOp({ type: 'delete', id, reason: card.reason }, card);
      case 'ma-toggle': state.manual.open = !state.manual.open; return render();
      case 'ma-submit': return manualSubmit();
      case 'stats-toggle': state.statsOpen = !state.statsOpen; return render();
      case 'sync-settings': state.syncOpen = true; return render();
      case 'sync-save':
        state.gh = { repo: $('#gh-repo').value.trim(), ref: $('#gh-ref').value.trim(), token: $('#gh-token').value.trim() };
        store.set(LS.gh, state.gh);
        state.syncOpen = false; state.syncMsg = '';
        toast('已儲存同步設定');
        return render();
      case 'sync-submit': return syncSubmit();
      default: return undefined;
    }
  }

  function onChange(e) {
    const el = e.target;
    const { action } = el.dataset;
    const id = el.dataset.id != null ? Number(el.dataset.id) : null;
    const card = id != null ? state.cards[id] : null;
    if (action === 'set-sub') {
      const it = card.items[Number(el.dataset.idx)];
      it.sub = el.value || null;
      card.msg = '';
      render();
    } else if (action === 'add-topic-select') {
      card.addTopic = el.value;
    } else if (action === 'delete-reason') {
      card.reason = el.value;
    } else if (action === 'ma-topic') {
      const set = new Set(state.manual.topics);
      if (el.checked) set.add(el.value); else set.delete(el.value);
      state.manual.topics = state.topics.filter((t) => set.has(t));
      const toggle = $('.ma-topic-toggle');
      if (toggle) {
        toggle.firstChild.textContent = state.manual.topics.length ? state.manual.topics.join('、') : '選擇議題（可複選）';
        toggle.classList.toggle('has-value', state.manual.topics.length > 0);
      }
    }
  }

  function onInput(e) {
    const el = e.target;
    if (el.id === 'search-input') {
      state.cal.query = el.value;
      state.cal.scope = 'all';
      if (state.view === 'date') render();
    } else if (el.id === 'month-input') {
      state.monthInput = el.value.replace(/\D/g, '').slice(0, 6);
      if (el.value !== state.monthInput) el.value = state.monthInput;
    } else if (el.id === 'ma-url') {
      state.manual.url = el.value;
    }
  }

  function onKeydown(e) {
    if (e.key === 'Enter' && e.target.id === 'month-input') goMonth();
    if (e.key === 'Enter' && e.target.id === 'ma-url') manualSubmit();
    if (e.key === 'Escape' && state.manual.open) { state.manual.open = false; render(); }
  }

  // ------------------------------------------------------------------ init
  async function init() {
    document.addEventListener('click', onClick);
    document.addEventListener('change', onChange);
    document.addEventListener('input', onInput);
    document.addEventListener('keydown', onKeydown);
    window.addEventListener('hashchange', () => {
      const v = location.hash.slice(1);
      if (['date', 'topic', 'trend', 'review'].includes(v) && v !== state.view) setView(v);
    });

    const hashView = location.hash.slice(1);
    state.view = ['date', 'topic', 'trend', 'review'].includes(hashView) ? hashView : store.get(LS.view, 'date');
    state.topic = store.get(LS.topic, state.topic);

    [state.mode] = await Promise.all([detectMode(), loadData()]);
    if (state.data.meta?.today && state.data.meta.today > state.today) state.today = state.data.meta.today;

    // 日曆預設：今天有新聞就選今天，否則選最近一個有新聞的日期
    const dates = new Set(state.data.articles.map((a) => a.date));
    const sel = dates.has(state.today) || !state.data.articles.length ? state.today : state.data.articles[0].date;
    const [y, m] = sel.split('-').map(Number);
    Object.assign(state.cal, { year: y, month: m, selected: sel, scope: 'day' });
    render();
  }

  init();
})();
