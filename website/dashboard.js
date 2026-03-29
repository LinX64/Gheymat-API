// ============================================================
// dashboard.js — Gheymat Dashboard
// ============================================================

const API_URL        = 'https://linx64.github.io/CurrencyCapPortal/latest.json';
const AUTH_API_URL   = window.AUTH_API_URL || 'https://gheymat-api-production.up.railway.app';
const BULK_CURRENCIES = ['usd', 'eur', 'gbp', 'try', 'aed', 'cny'];

// ---- i18n (minimal, bilingual) ----
const T = {
    en: {
        tabRates: 'Rates', tabPredict: 'AI Predictions', tabAccount: 'Account',
        ratesTitle: 'Exchange Rates', ratesSub: 'All currencies — prices in Toman',
        thCurrency: 'Currency', thBuy: 'Buy', thSell: 'Sell', thChange: 'Change', thUpdated: 'Updated',
        ratesLive: 'Live', searchPlaceholder: 'Search currency…', ratesLoading: 'Loading rates…',
        predictTitle: 'AI Currency Predictions', predictSub: 'Live 7-day forecasts powered by machine learning',
        predictCurrencyLabel: 'Currency', predictDaysLabel: 'Forecast horizon',
        predictRunBtn: 'Run Prediction', predictRunning: 'Running…',
        bulkTitle: 'Quick Overview', bulkSub: '7-day forecast for key currencies', bulkRefresh: 'Refresh All',
        currentPrice: 'Current', predicted: 'Predicted', confidence: 'Confidence', trend: 'Trend',
        trendUp: '↑ Up', trendDown: '↓ Down', trendNeutral: '→ Neutral',
        gateTitleLogin: 'Sign in to access AI Predictions',
        gateDescLogin: 'Create a free account to get started.',
        gateLoginBtn: 'Sign In / Register',
        gateTitlePremium: 'Upgrade to Premium',
        gateDescPremium: 'Live AI predictions are a Premium feature.',
        gateUpgradeBtn: 'Upgrade to Premium',
        accountTitle: 'Your Account',
        accountGateTitle: 'Sign in to view your account',
        upgradeTitle: 'Upgrade to Premium',
        upgradeSub: 'Unlock AI predictions & advanced analytics',
        upgradeFeatures: ['Live AI predictions (LSTM + ensemble)', '7, 14 & 30-day forecasts', 'Confidence intervals & trend analysis', 'Priority API access'],
        upgradeBtn: 'Upgrade Now',
        premiumActiveTitle: "You're on Premium",
        premiumActiveSub: 'You have full access to all AI prediction features.',
        goPredictLink: 'Go to AI Predictions →',
        memberSince: 'Member since',
        logout: 'Sign Out', login: 'Sign In',
        free: 'Free', premium: '★ Premium',
        justNow: 'just now', minutesAgo: 'min ago', hoursAgo: 'h ago',
        predError: 'Prediction failed. Please try again.',
        noData: 'No data available.',
        dayLabels: { 7: '7 days', 14: '14 days', 30: '30 days' }
    },
    fa: {
        tabRates: 'نرخ‌ها', tabPredict: 'پیش‌بینی هوش مصنوعی', tabAccount: 'حساب',
        ratesTitle: 'نرخ ارز', ratesSub: 'همه ارزها — قیمت به تومان',
        thCurrency: 'ارز', thBuy: 'خرید', thSell: 'فروش', thChange: 'تغییر', thUpdated: 'به‌روزرسانی',
        ratesLive: 'زنده', searchPlaceholder: 'جستجوی ارز…', ratesLoading: 'در حال بارگذاری…',
        predictTitle: 'پیش‌بینی ارز با هوش مصنوعی', predictSub: 'پیش‌بینی ۷ روزه با یادگیری ماشین',
        predictCurrencyLabel: 'ارز', predictDaysLabel: 'افق پیش‌بینی',
        predictRunBtn: 'اجرای پیش‌بینی', predictRunning: 'در حال اجرا…',
        bulkTitle: 'نمای کلی', bulkSub: 'پیش‌بینی ۷ روزه برای ارزهای اصلی', bulkRefresh: 'به‌روزرسانی',
        currentPrice: 'فعلی', predicted: 'پیش‌بینی', confidence: 'اطمینان', trend: 'روند',
        trendUp: '↑ صعودی', trendDown: '↓ نزولی', trendNeutral: '→ خنثی',
        gateTitleLogin: 'برای دسترسی به پیش‌بینی وارد شوید',
        gateDescLogin: 'یک حساب رایگان ایجاد کنید.',
        gateLoginBtn: 'ورود / ثبت‌نام',
        gateTitlePremium: 'ارتقا به پریمیوم',
        gateDescPremium: 'پیش‌بینی زنده هوش مصنوعی یک ویژگی پریمیوم است.',
        gateUpgradeBtn: 'ارتقا به پریمیوم',
        accountTitle: 'حساب شما',
        accountGateTitle: 'برای مشاهده حساب وارد شوید',
        upgradeTitle: 'ارتقا به پریمیوم',
        upgradeSub: 'پیش‌بینی هوش مصنوعی را باز کنید',
        upgradeFeatures: ['پیش‌بینی زنده هوش مصنوعی', 'پیش‌بینی ۷، ۱۴ و ۳۰ روزه', 'بازه اطمینان و تحلیل روند', 'دسترسی اولویت‌دار به API'],
        upgradeBtn: 'ارتقا',
        premiumActiveTitle: 'شما پریمیوم هستید',
        premiumActiveSub: 'به تمام ویژگی‌های پیش‌بینی هوش مصنوعی دسترسی دارید.',
        goPredictLink: 'رفتن به پیش‌بینی‌ها ←',
        memberSince: 'عضو از',
        logout: 'خروج', login: 'ورود',
        free: 'رایگان', premium: '★ پریمیوم',
        justNow: 'همین الان', minutesAgo: 'دقیقه پیش', hoursAgo: 'ساعت پیش',
        predError: 'پیش‌بینی ناموفق بود. دوباره تلاش کنید.',
        noData: 'اطلاعاتی موجود نیست.',
        dayLabels: { 7: '۷ روز', 14: '۱۴ روز', 30: '۳۰ روز' }
    }
};

// ---- state ----
let currentLang  = localStorage.getItem('lang') || 'en';
let currentTheme = localStorage.getItem('theme') || 'dark';
let allRatesData = [];
let activeTab    = 'rates';

const auth = {
    get token()  { return localStorage.getItem('gheymat_token'); },
    get refresh() { return localStorage.getItem('gheymat_refresh'); },
    get user()   { try { return JSON.parse(localStorage.getItem('gheymat_user') || 'null'); } catch { return null; } },
    save(d) {
        localStorage.setItem('gheymat_token', d.access_token);
        if (d.refresh_token) localStorage.setItem('gheymat_refresh', d.refresh_token);
        localStorage.setItem('gheymat_user', JSON.stringify(d.user));
    },
    clear() {
        localStorage.removeItem('gheymat_token');
        localStorage.removeItem('gheymat_refresh');
        localStorage.removeItem('gheymat_user');
    },
    isPremium()  { return this.user?.tier === 'premium'; },
    isLoggedIn() { return !!this.token && !!this.user; }
};

// ---- helpers ----
const t = () => T[currentLang];
const $ = id => document.getElementById(id);
const fmt = n => n ? new Intl.NumberFormat('en-US').format(Math.round(n)) : '—';

function timeAgo(isoStr) {
    const diff = (Date.now() - new Date(isoStr).getTime()) / 1000;
    if (diff < 90) return t().justNow;
    if (diff < 3600) return `${Math.round(diff / 60)} ${t().minutesAgo}`;
    return `${Math.round(diff / 3600)} ${t().hoursAgo}`;
}

async function authFetch(path, opts = {}) {
    const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
    if (auth.token) headers['Authorization'] = `Bearer ${auth.token}`;
    return fetch(`${AUTH_API_URL}${path}`, { ...opts, headers });
}

// ---- theme / lang ----
function applyTheme(theme) {
    currentTheme = theme;
    localStorage.setItem('theme', theme);
    document.documentElement.setAttribute('data-theme', theme);
    const btn = $('themeToggle');
    if (btn) btn.setAttribute('aria-pressed', theme === 'light' ? 'true' : 'false');
}

function applyLang(lang) {
    currentLang = lang;
    localStorage.setItem('lang', lang);
    document.documentElement.setAttribute('lang', lang);
    document.documentElement.setAttribute('dir', lang === 'fa' ? 'rtl' : 'ltr');
    const lt = $('langToggle')?.querySelector('.lang-text');
    if (lt) lt.textContent = lang === 'en' ? 'فا' : 'EN';
    updateAllText();
}

function updateAllText() {
    const tr = t();
    // tabs
    setText('tabRatesLabel', tr.tabRates);
    setText('tabPredictLabel', tr.tabPredict);
    setText('tabAccountLabel', tr.tabAccount);
    // rates panel
    setText('ratesPanelTitle', tr.ratesTitle);
    setText('ratesPanelSubtitle', tr.ratesSub);
    setText('ratesLiveLabel', tr.ratesLive);
    setAttr('ratesSearch', 'placeholder', tr.searchPlaceholder);
    setText('thCurrency', tr.thCurrency);
    setText('thBuy', tr.thBuy);
    setText('thSell', tr.thSell);
    setText('thChange', tr.thChange);
    setText('thUpdated', tr.thUpdated);
    // predict panel
    setText('predictPanelTitle', tr.predictTitle);
    setText('predictPanelSubtitle', tr.predictSub);
    setText('predictCurrencyLabel', tr.predictCurrencyLabel);
    setText('predictDaysLabel', tr.predictDaysLabel);
    setAttr('predictRunBtn', 'data-label', tr.predictRunBtn);
    if ($('predictRunBtn') && !$('predictRunBtn').disabled) $('predictRunBtn').querySelector('span') && ($('predictRunBtn').querySelector('span').textContent = tr.predictRunBtn);
    setText('bulkTitle', tr.bulkTitle);
    setText('bulkSub', tr.bulkSub);
    // gates
    setText('gateTitleLogin', tr.gateTitleLogin);
    setText('gateDescLogin', tr.gateDescLogin);
    setText('gateLoginBtn', tr.gateLoginBtn);
    setText('gateTitlePremium', tr.gateTitlePremium);
    setText('gateDescPremium', tr.gateDescPremium);
    setText('gateUpgradeBtn', tr.gateUpgradeBtn);
    // account
    setText('accountPanelTitle', tr.accountTitle);
    setText('accountGateTitle', tr.accountGateTitle);
    setText('upgradeTitle', tr.upgradeTitle);
    setText('upgradeSub', tr.upgradeSub);
    setText('upgradeCtaBtn', tr.upgradeBtn);
    setText('premiumActiveTitle', tr.premiumActiveTitle);
    setText('premiumActiveSub', tr.premiumActiveSub);
    setText('goPredictLink', tr.goPredictLink);
    // nav
    setText('dashLogoutBtn', tr.logout);
    setText('dashLoginBtn', tr.login);
    // re-render rates rows if loaded
    if (allRatesData.length) renderRates(allRatesData);
}

function setText(id, val) { const el = $(id); if (el && val !== undefined) el.textContent = val; }
function setAttr(id, attr, val) { const el = $(id); if (el && val !== undefined) el.setAttribute(attr, val); }

// ---- Tab switching ----
function switchTab(name) {
    activeTab = name;
    ['rates', 'predict', 'account'].forEach(n => {
        const tab   = $(`tab${capitalize(n)}`);
        const panel = $(`panel${capitalize(n)}`);
        const active = n === name;
        if (tab)   { tab.classList.toggle('active', active); tab.setAttribute('aria-selected', String(active)); }
        if (panel) { panel.classList.toggle('active', active); panel.hidden = !active; }
    });
    if (name === 'predict') renderPredictGate();
    if (name === 'account') renderAccountPanel();
}

function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

// ---- Auth UI ----
function updateNavAuth() {
    const loggedIn = auth.isLoggedIn();
    const loginBtn  = $('dashLoginBtn');
    const logoutBtn = $('dashLogoutBtn');
    const userEl    = $('dashUser');
    const tierEl    = $('dashUserTier');
    const nameEl    = $('dashUserName');

    if (loggedIn) {
        if (loginBtn)  loginBtn.style.display = 'none';
        if (logoutBtn) logoutBtn.style.display = '';
        if (userEl)    userEl.style.display = 'flex';
        if (tierEl) {
            tierEl.textContent = auth.isPremium() ? t().premium : t().free;
            tierEl.className = 'dash-user-tier' + (auth.isPremium() ? ' premium' : '');
        }
        if (nameEl) nameEl.textContent = auth.user.name || auth.user.email;
    } else {
        if (loginBtn)  loginBtn.style.display = '';
        if (logoutBtn) logoutBtn.style.display = 'none';
        if (userEl)    userEl.style.display = 'none';
    }
}

// ---- Rates ----
async function loadRates() {
    const body = $('ratesBody');
    if (body) body.innerHTML = `<tr><td colspan="5" class="rates-loading">${t().ratesLoading}</td></tr>`;
    try {
        const res  = await fetch(`${API_URL}?t=${Date.now()}`, { cache: 'no-store' });
        const data = await res.json();
        allRatesData = data.filter(item => item.ty === 'cu');
        renderRates(allRatesData);
    } catch (e) {
        if (body) body.innerHTML = `<tr><td colspan="5" class="rates-loading">${t().noData}</td></tr>`;
    }
}

const CURRENCY_NAMES = {
    en: { usd:'US Dollar',eur:'Euro',gbp:'British Pound',try:'Turkish Lira',aed:'UAE Dirham',cny:'Chinese Yuan',jpy:'Japanese Yen',cad:'Canadian Dollar',aud:'Australian Dollar',chf:'Swiss Franc',rub:'Russian Ruble',inr:'Indian Rupee',krw:'South Korean Won',sek:'Swedish Krona',nok:'Norwegian Krone',dkk:'Danish Krone',sgd:'Singapore Dollar',hkd:'Hong Kong Dollar',nzd:'New Zealand Dollar',mxn:'Mexican Peso',brl:'Brazilian Real',zar:'South African Rand',thb:'Thai Baht',pln:'Polish Zloty',czk:'Czech Koruna',huf:'Hungarian Forint',ron:'Romanian Leu',ils:'Israeli Shekel',php:'Philippine Peso',myr:'Malaysian Ringgit',idr:'Indonesian Rupiah',clp:'Chilean Peso',cop:'Colombian Peso',ars:'Argentine Peso',iqd:'Iraqi Dinar',sar:'Saudi Riyal',kwd:'Kuwaiti Dinar',qar:'Qatari Riyal',omr:'Omani Rial',bhd:'Bahraini Dinar',azn:'Azerbaijani Manat',gel:'Georgian Lari',amd:'Armenian Dram',afn:'Afghan Afghani' },
    fa: { usd:'دلار آمریکا',eur:'یورو',gbp:'پوند انگلیس',try:'لیر ترکیه',aed:'درهم امارات',cny:'یوان چین',jpy:'ین ژاپن',cad:'دلار کانادا',aud:'دلار استرالیا',chf:'فرانک سوئیس',rub:'روبل روسیه',inr:'روپیه هند',krw:'وون کره جنوبی',sek:'کرون سوئد',nok:'کرون نروژ',dkk:'کرون دانمارک',sgd:'دلار سنگاپور',hkd:'دلار هنگ کنگ',nzd:'دلار نیوزیلند',mxn:'پزو مکزیک',brl:'رئال برزیل',zar:'راند آفریقای جنوبی',thb:'بات تایلند',pln:'زلوتی لهستان',czk:'کرون جمهوری چک',huf:'فورینت مجارستان',ron:'لئو رومانی',ils:'شکل اسرائیل',php:'پزو فیلیپین',myr:'رینگیت مالزی',idr:'روپیه اندونزی',clp:'پزو شیلی',cop:'پزو کلمبیا',ars:'پزو آرژانتین',iqd:'دینار عراق',sar:'ریال عربستان',kwd:'دینار کویت',qar:'ریال قطر',omr:'ریال عمان',bhd:'دینار بحرین',azn:'منات آذربایجان',gel:'لاری گرجستان',amd:'درام ارمنستان',afn:'افغانی افغانستان' }
};

let prevPrices = {};

function renderRates(data) {
    const body = $('ratesBody');
    if (!body) return;
    const search = ($('ratesSearch')?.value || '').toLowerCase();
    const tr = t();

    const rows = data
        .filter(c => {
            if (!search) return true;
            const code = c.ab.toLowerCase();
            const name = (CURRENCY_NAMES[currentLang][code] || c.en || '').toLowerCase();
            return code.includes(search) || name.includes(search);
        })
        .map(c => {
            const ps  = c.ps?.[c.ps.length - 1] || {};
            const buy  = ps.bp || 0;
            const sell = ps.sp || 0;
            const price = sell || buy;
            const code  = c.ab.toLowerCase();

            let changePct = 0;
            if (prevPrices[code] && price) {
                changePct = ((price - prevPrices[code]) / prevPrices[code]) * 100;
            }
            prevPrices[code] = price;

            const isUp   = changePct > 0;
            const isDown = changePct < 0;
            const changeHtml = changePct !== 0
                ? `<span class="rate-change ${isUp ? 'positive' : 'negative'}">${isUp ? '+' : ''}${changePct.toFixed(2)}%</span>`
                : '<span class="rate-change neutral">—</span>';

            const name = CURRENCY_NAMES[currentLang][code] || c.en || code.toUpperCase();
            const ts   = ps.ts ? timeAgo(ps.ts) : '—';

            return `<tr class="rates-row">
                <td class="rates-td rates-td-currency">
                    <span class="rate-flag">${c.av || ''}</span>
                    <span class="rate-code">${c.ab.toUpperCase()}</span>
                    <span class="rate-name">${name}</span>
                </td>
                <td class="rates-td rates-td-num">${fmt(buy)}</td>
                <td class="rates-td rates-td-num">${fmt(sell)}</td>
                <td class="rates-td rates-td-num">${changeHtml}</td>
                <td class="rates-td rates-td-time">${ts}</td>
            </tr>`;
        }).join('');

    body.innerHTML = rows || `<tr><td colspan="5" class="rates-loading">${tr.noData}</td></tr>`;
}

// ---- Predictions ----
function renderPredictGate() {
    const gateLogin   = $('predictGateLogin');
    const gatePremium = $('predictGatePremium');
    const content     = $('predictContent');

    if (!auth.isLoggedIn()) {
        show(gateLogin); hide(gatePremium); hide(content);
    } else if (!auth.isPremium()) {
        hide(gateLogin); show(gatePremium); hide(content);
    } else {
        hide(gateLogin); hide(gatePremium); show(content);
        loadBulkPredictions();
    }
}

async function runPrediction(e) {
    e.preventDefault();
    const currency = $('predictCurrency')?.value;
    const days     = parseInt($('predictDays')?.value || '14', 10);
    const btn      = $('predictRunBtn');
    const result   = $('predictResult');
    if (!btn || !result) return;

    btn.disabled = true;
    btn.textContent = t().predictRunning;
    result.innerHTML = '<div class="pred-loading">Running prediction…</div>';

    try {
        const res  = await authFetch('/api/v1/predict', {
            method: 'POST',
            body: JSON.stringify({ currencyCode: currency, daysAhead: days, useML: true })
        });
        const data = await res.json();

        if (!res.ok) throw new Error(data.error || t().predError);
        result.innerHTML = buildPredResultHTML(data, days);
    } catch (err) {
        result.innerHTML = `<div class="pred-error">${err.message}</div>`;
    } finally {
        btn.disabled = false;
        btn.textContent = t().predictRunBtn;
    }
}

function buildPredResultHTML(data, days) {
    const tr = t();
    const preds = data.predictions || [];
    const cur   = data.currentPrice || {};
    const currentSell = cur.sell || cur.buy || 0;

    const last = preds[preds.length - 1] || preds[0] || {};
    const predPrice = last.price || 0;
    const confidence = last.confidence ? (last.confidence * 100).toFixed(0) : '—';
    const trend = last.trend || 'neutral';
    const trendLabel = trend === 'up' ? tr.trendUp : trend === 'down' ? tr.trendDown : tr.trendNeutral;
    const pct = currentSell > 0 ? (((predPrice - currentSell) / currentSell) * 100).toFixed(1) : 0;
    const isUp = parseFloat(pct) > 0;
    const flag = data.flag || '';
    const dayLabel = tr.dayLabels[days] || `${days}d`;

    const timeline = preds.slice(0, 7).map((p, i) => {
        const d = new Date(); d.setDate(d.getDate() + i + 1);
        const label = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        const pChange = currentSell > 0 ? (((p.price - currentSell) / currentSell) * 100).toFixed(1) : 0;
        const isU = parseFloat(pChange) > 0;
        return `<div class="pred-timeline-item">
            <span class="pred-tl-date">${label}</span>
            <span class="pred-tl-price">${fmt(p.price)}</span>
            <span class="pred-tl-change ${isU ? 'positive' : 'negative'}">${isU ? '+' : ''}${pChange}%</span>
        </div>`;
    }).join('');

    return `
    <div class="pred-result-card">
        <div class="pred-result-header">
            <div class="pred-result-currency">
                <span class="pred-flag-lg">${flag}</span>
                <div>
                    <span class="pred-code-lg">${(data.currency || '').toUpperCase()}</span>
                    <span class="pred-horizon">${dayLabel} ${tr.predicted.toLowerCase()}</span>
                </div>
            </div>
            <div class="pred-result-trend ${trend}">${trendLabel}</div>
        </div>
        <div class="pred-result-numbers">
            <div class="pred-result-num">
                <span class="pred-result-label">${tr.currentPrice}</span>
                <span class="pred-result-val">${fmt(currentSell)}</span>
            </div>
            <div class="pred-result-num">
                <span class="pred-result-label">${tr.predicted} (${dayLabel})</span>
                <span class="pred-result-val ${isUp ? 'positive' : 'negative'}">${fmt(predPrice)}</span>
            </div>
            <div class="pred-result-num">
                <span class="pred-result-label">${tr.confidence}</span>
                <span class="pred-result-val">${confidence}%</span>
            </div>
            <div class="pred-result-num">
                <span class="pred-result-label">Change</span>
                <span class="pred-result-val ${isUp ? 'positive' : 'negative'}">${isUp ? '+' : ''}${pct}%</span>
            </div>
        </div>
        ${timeline ? `<div class="pred-timeline">${timeline}</div>` : ''}
    </div>`;
}

async function loadBulkPredictions() {
    const grid = $('bulkGrid');
    if (!grid) return;
    grid.innerHTML = '<div class="pred-loading">Loading predictions…</div>';

    const results = await Promise.allSettled(
        BULK_CURRENCIES.map(code =>
            authFetch('/api/v1/predict', {
                method: 'POST',
                body: JSON.stringify({ currencyCode: code, daysAhead: 7, useML: true })
            }).then(r => r.json().then(d => ({ code, data: d, ok: r.ok })))
        )
    );

    const tr = t();
    const cards = results
        .filter(r => r.status === 'fulfilled' && r.value.ok)
        .map(r => {
            const { code, data } = r.value;
            const preds = data.predictions || [];
            const last  = preds[preds.length - 1] || preds[0] || {};
            const cur   = data.currentPrice?.sell || data.currentPrice?.buy || 0;
            const pred  = last.price || 0;
            const pct   = cur > 0 ? (((pred - cur) / cur) * 100).toFixed(1) : 0;
            const isUp  = parseFloat(pct) > 0;
            const conf  = last.confidence ? (last.confidence * 100).toFixed(0) : '—';
            const trend = last.trend || 'neutral';
            const trendLabel = trend === 'up' ? tr.trendUp : trend === 'down' ? tr.trendDown : tr.trendNeutral;
            const flag  = data.flag || '';
            const name  = CURRENCY_NAMES[currentLang][code] || code.toUpperCase();

            return `<div class="prediction-card" role="listitem">
                <div class="pred-header">
                    <div class="pred-currency">
                        <span class="pred-flag">${flag}</span>
                        <div>
                            <span class="pred-code">${code.toUpperCase()}</span>
                            <span class="pred-name">${name}</span>
                        </div>
                    </div>
                    <div class="pred-trend ${trend}">${trendLabel}</div>
                </div>
                <div class="pred-prices">
                    <div class="pred-price-item">
                        <span class="pred-label">${tr.currentPrice}</span>
                        <span class="pred-value">${fmt(cur)}</span>
                    </div>
                    <div class="pred-price-item">
                        <span class="pred-label">${tr.predicted} (7d)</span>
                        <span class="pred-value ${isUp ? 'positive' : 'negative'}">${fmt(pred)}</span>
                    </div>
                </div>
                <div class="pred-footer">
                    <span class="pred-confidence">${tr.confidence}: ${conf}%</span>
                    <span class="pred-change ${isUp ? 'positive' : 'negative'}">${isUp ? '+' : ''}${pct}%</span>
                </div>
            </div>`;
        }).join('');

    grid.innerHTML = cards || `<p class="predictions-error">${tr.noData}</p>`;
}

// ---- Account ----
function renderAccountPanel() {
    const gateLogin = $('accountGateLogin');
    const content   = $('accountContent');
    if (!auth.isLoggedIn()) {
        show(gateLogin); hide(content); return;
    }
    hide(gateLogin); show(content);

    const user = auth.user;
    const initial = (user.name || user.email || '?').charAt(0).toUpperCase();
    const el = $('accountAvatar');
    if (el) el.textContent = initial;

    setText('accountName', user.name || '—');
    setText('accountEmail', user.email || '—');
    const since = user.createdAt ? new Date(user.createdAt).toLocaleDateString() : '';
    setText('accountSince', since ? `${t().memberSince} ${since}` : '');

    const badge = $('accountTierBadge');
    if (badge) {
        badge.textContent = auth.isPremium() ? t().premium : t().free;
        badge.className = 'account-tier-badge' + (auth.isPremium() ? ' premium' : '');
    }

    const upgradeCard = $('upgradeCard');
    const premCard    = $('premiumActiveCard');
    if (auth.isPremium()) {
        hide(upgradeCard); show(premCard);
    } else {
        show(upgradeCard); hide(premCard);
        // refresh upgrade features list
        const ul = $('upgradeFeatures');
        if (ul) ul.innerHTML = t().upgradeFeatures.map(f => `<li>${f}</li>`).join('');
    }
}

// ---- Auth Modal ----
function openAuthModal() {
    const m = $('authModal');
    if (m) { m.style.display = 'flex'; document.body.style.overflow = 'hidden'; }
}

function closeAuthModal() {
    const m = $('authModal');
    if (m) { m.style.display = 'none'; document.body.style.overflow = ''; }
}

function switchAuthTab(tab) {
    const lf = $('loginForm'), rf = $('registerForm');
    const tl = $('tabLogin'),  tr2 = $('tabRegister');
    if (!lf) return;
    if (tab === 'login') {
        lf.style.display = 'block'; rf.style.display = 'none';
        tl.classList.add('active'); tr2.classList.remove('active');
    } else {
        lf.style.display = 'none'; rf.style.display = 'block';
        tl.classList.remove('active'); tr2.classList.add('active');
    }
}

// ---- DOM helpers ----
function show(el) { if (el) el.style.display = ''; }
function hide(el) { if (el) el.style.display = 'none'; }

// ---- Init ----
document.addEventListener('DOMContentLoaded', () => {
    // Apply saved prefs
    document.documentElement.setAttribute('data-theme', currentTheme);
    document.documentElement.setAttribute('lang', currentLang);
    document.documentElement.setAttribute('dir', currentLang === 'fa' ? 'rtl' : 'ltr');

    // Update all text
    updateAllText();
    updateNavAuth();

    // Tab buttons
    $('tabRates')?.addEventListener('click',   () => switchTab('rates'));
    $('tabPredict')?.addEventListener('click', () => switchTab('predict'));
    $('tabAccount')?.addEventListener('click', () => switchTab('account'));

    // Theme
    $('themeToggle')?.addEventListener('click', () => applyTheme(currentTheme === 'dark' ? 'light' : 'dark'));

    // Lang
    $('langToggle')?.addEventListener('click', () => applyLang(currentLang === 'en' ? 'fa' : 'en'));

    // Nav auth
    $('dashLoginBtn')?.addEventListener('click', openAuthModal);
    $('dashLogoutBtn')?.addEventListener('click', () => { auth.clear(); updateNavAuth(); renderPredictGate(); renderAccountPanel(); });

    // Gate buttons
    $('gateLoginBtn')?.addEventListener('click',    openAuthModal);
    $('gateUpgradeBtn')?.addEventListener('click',  () => switchTab('account'));
    $('accountLoginBtn')?.addEventListener('click', openAuthModal);
    $('upgradeCtaBtn')?.addEventListener('click',   () => alert('Premium upgrade coming soon!'));
    $('goPredictLink')?.addEventListener('click',   (e) => { e.preventDefault(); switchTab('predict'); });

    // Auth modal
    $('modalClose')?.addEventListener('click', closeAuthModal);
    $('authModal')?.addEventListener('click', e => { if (e.target.id === 'authModal') closeAuthModal(); });
    $('tabLogin')?.addEventListener('click',    () => switchAuthTab('login'));
    $('tabRegister')?.addEventListener('click', () => switchAuthTab('register'));

    $('loginForm')?.addEventListener('submit', async e => {
        e.preventDefault();
        const email = $('loginEmail').value;
        const password = $('loginPassword').value;
        const errEl = $('loginError'), btn = $('loginSubmit');
        errEl.textContent = ''; btn.disabled = true; btn.textContent = '…';
        try {
            const res  = await authFetch('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Login failed');
            auth.save(data);
            closeAuthModal();
            updateNavAuth();
            if (activeTab === 'predict') renderPredictGate();
            if (activeTab === 'account') renderAccountPanel();
        } catch (err) { errEl.textContent = err.message; }
        finally { btn.disabled = false; btn.textContent = 'Sign In'; }
    });

    $('registerForm')?.addEventListener('submit', async e => {
        e.preventDefault();
        const name = $('regName').value, email = $('regEmail').value, password = $('regPassword').value;
        const errEl = $('registerError'), btn = $('registerSubmit');
        errEl.textContent = ''; btn.disabled = true; btn.textContent = '…';
        try {
            const res  = await authFetch('/api/auth/register', { method: 'POST', body: JSON.stringify({ name, email, password }) });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Registration failed');
            auth.save(data);
            closeAuthModal();
            updateNavAuth();
            if (activeTab === 'predict') renderPredictGate();
            if (activeTab === 'account') renderAccountPanel();
        } catch (err) { errEl.textContent = err.message; }
        finally { btn.disabled = false; btn.textContent = 'Create Account'; }
    });

    // Predict form
    $('predictForm')?.addEventListener('submit', runPrediction);
    $('bulkRunBtn')?.addEventListener('click', loadBulkPredictions);

    // Rates search
    $('ratesSearch')?.addEventListener('input', () => renderRates(allRatesData));

    // Load initial data
    loadRates();
    setInterval(loadRates, 30000);
});
