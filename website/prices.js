// ============================================================
// prices.js — Gheymat All Prices Page
// ============================================================

const _isGitHubPages = window.location.hostname.includes('github.io');
const API_URL = _isGitHubPages
    ? 'https://linx64.github.io/CurrencyCapPortal/api/latest.json'
    : '/api/latest';

const T = {
    en: {
        title: 'All Currency Prices',
        subtitle: 'Real-time exchange rates for all available currencies',
        backButton: 'Back to Home',
        live: 'Live',
        loading: 'Loading latest prices...',
        error: 'Failed to load prices. Please try again.',
        buy: 'Buy', sell: 'Sell',
        home: 'Home',
        currencies: {
            usd:'US Dollar',eur:'Euro',gbp:'British Pound',try:'Turkish Lira',
            aed:'UAE Dirham',cny:'Chinese Yuan',jpy:'Japanese Yen',cad:'Canadian Dollar',
            aud:'Australian Dollar',chf:'Swiss Franc',rub:'Russian Ruble',inr:'Indian Rupee',
            krw:'South Korean Won',sek:'Swedish Krona',nok:'Norwegian Krone',dkk:'Danish Krone',
            sgd:'Singapore Dollar',hkd:'Hong Kong Dollar',nzd:'New Zealand Dollar',
            mxn:'Mexican Peso',brl:'Brazilian Real',zar:'South African Rand',thb:'Thai Baht',
            pln:'Polish Zloty',czk:'Czech Koruna',huf:'Hungarian Forint',ron:'Romanian Leu',
            ils:'Israeli Shekel',php:'Philippine Peso',myr:'Malaysian Ringgit',
            idr:'Indonesian Rupiah',clp:'Chilean Peso',cop:'Colombian Peso',
            ars:'Argentine Peso',iqd:'Iraqi Dinar',sar:'Saudi Riyal',kwd:'Kuwaiti Dinar',
            qar:'Qatari Riyal',omr:'Omani Rial',bhd:'Bahraini Dinar',azn:'Azerbaijani Manat',
            gel:'Georgian Lari',amd:'Armenian Dram',afn:'Afghan Afghani'
        }
    },
    fa: {
        title: 'همه قیمت‌های ارز',
        subtitle: 'نرخ‌های لحظه‌ای برای همه ارزهای موجود',
        backButton: 'بازگشت به خانه',
        live: 'زنده',
        loading: 'در حال بارگذاری...',
        error: 'بارگذاری قیمت‌ها ناموفق بود. دوباره تلاش کنید.',
        buy: 'خرید', sell: 'فروش',
        home: 'خانه',
        currencies: {
            usd:'دلار آمریکا',eur:'یورو',gbp:'پوند انگلیس',try:'لیر ترکیه',
            aed:'درهم امارات',cny:'یوان چین',jpy:'ین ژاپن',cad:'دلار کانادا',
            aud:'دلار استرالیا',chf:'فرانک سوئیس',rub:'روبل روسیه',inr:'روپیه هند',
            krw:'وون کره جنوبی',sek:'کرون سوئد',nok:'کرون نروژ',dkk:'کرون دانمارک',
            sgd:'دلار سنگاپور',hkd:'دلار هنگ‌کنگ',nzd:'دلار نیوزیلند',
            mxn:'پزو مکزیک',brl:'رئال برزیل',zar:'رند آفریقای جنوبی',thb:'بات تایلند',
            pln:'زلوتی لهستان',czk:'کرون چک',huf:'فورینت مجارستان',ron:'لئو رومانی',
            ils:'شکل اسرائیل',php:'پزو فیلیپین',myr:'رینگیت مالزی',
            idr:'روپیه اندونزی',clp:'پزو شیلی',cop:'پزو کلمبیا',
            ars:'پزو آرژانتین',iqd:'دینار عراق',sar:'ریال عربستان',kwd:'دینار کویت',
            qar:'ریال قطر',omr:'ریال عمان',bhd:'دینار بحرین',azn:'مانات آذربایجان',
            gel:'لاری گرجستان',amd:'درام ارمنستان',afn:'افغانی افغانستان'
        }
    }
};

// ---- State ----
let currentLang = localStorage.getItem('lang') || 'en';
let currentTheme = localStorage.getItem('theme') || 'dark';
let allCurrencies = [];

// ---- Utilities ----
function formatPrice(n) {
    if (!n && n !== 0) return '—';
    return Number(n).toLocaleString('en-US');
}

function applyLang() {
    const t = T[currentLang];
    document.documentElement.lang = currentLang;
    document.documentElement.dir = currentLang === 'fa' ? 'rtl' : 'ltr';

    const el = id => document.getElementById(id);
    const setTxt = (elemId, txt) => { const e = el(elemId); if (e) e.textContent = txt; };

    setTxt('pageTitle', t.title);
    setTxt('pageSubtitle', t.subtitle);
    setTxt('backBtnLabel', t.backButton);
    setTxt('liveLabel', t.live);

    const langToggle = document.getElementById('langToggle');
    if (langToggle) langToggle.querySelector('.lang-text').textContent = currentLang === 'fa' ? 'EN' : 'فا';

    // Re-render if data is loaded
    if (allCurrencies.length > 0) renderGrid(allCurrencies);
}

function applyTheme() {
    document.documentElement.setAttribute('data-theme', currentTheme);
    const btn = document.getElementById('themeToggle');
    if (btn) btn.setAttribute('aria-pressed', currentTheme === 'light' ? 'true' : 'false');
}

function id(x) { return document.getElementById(x); }

// ---- Fetch & Render ----
async function loadPrices() {
    const grid = id('pricesGridFull');
    if (!grid) return;

    const t = T[currentLang];
    grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;color:var(--text-secondary);padding:40px">${t.loading}</div>`;

    try {
        const res = await fetch(API_URL);
        if (!res.ok) throw new Error('Network error');
        const data = await res.json();

        allCurrencies = (Array.isArray(data) ? data : (data.currencies || [])).filter(c => c.ty === 'cu');

        renderGrid(allCurrencies);
    } catch (err) {
        grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;color:var(--color-negative);padding:40px">${t.error}</div>`;
    }
}

function renderGrid(currencies) {
    const grid = id('pricesGridFull');
    if (!grid) return;
    const t = T[currentLang];

    if (!currencies.length) {
        grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;color:var(--text-secondary);padding:40px">${t.error}</div>`;
        return;
    }

    grid.innerHTML = currencies.map(c => {
        const latest = c.ps?.[c.ps.length - 1] || {};
        const bp = latest.bp || 0;
        const sp = latest.sp || 0;
        const code = (c.ab || '').toUpperCase();
        const name = t.currencies[c.ab?.toLowerCase()] || c.en || code;

        return `
        <div class="price-item" role="listitem">
            <div class="price-info">
                <div class="currency-flag" aria-hidden="true">${c.av || ''}</div>
                <div class="currency-details">
                    <div class="currency-code">${code}</div>
                    <div class="currency-name">${name}</div>
                </div>
            </div>
            <div class="price-value">
                <div class="price-buysell">
                    <div class="price-side">
                        <span class="price-side-label">${t.buy}</span>
                        <span class="price-amount">${formatPrice(bp)}</span>
                    </div>
                    <div class="price-side-divider"></div>
                    <div class="price-side">
                        <span class="price-side-label">${t.sell}</span>
                        <span class="price-amount">${formatPrice(sp)}</span>
                    </div>
                </div>
            </div>
        </div>`;
    }).join('');
}

// ---- Theme Toggle ----
function initThemeToggle() {
    applyTheme();
    id('themeToggle')?.addEventListener('click', () => {
        currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
        localStorage.setItem('theme', currentTheme);
        applyTheme();
    });
}

// ---- Lang Toggle ----
function initLangToggle() {
    id('langToggle')?.addEventListener('click', () => {
        currentLang = currentLang === 'en' ? 'fa' : 'en';
        localStorage.setItem('lang', currentLang);
        applyLang();
    });
}

// ---- Init ----
document.addEventListener('DOMContentLoaded', () => {
    initThemeToggle();
    initLangToggle();
    applyLang();
    loadPrices();

    // Auto-refresh every 30 seconds
    setInterval(loadPrices, 30_000);
});
