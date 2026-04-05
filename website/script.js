// ==========================================
// Internationalization (i18n)
// ==========================================

const translations = {
    en: {
        meta: {
            title: 'Gheymat - AI-Powered Currency Predictions',
            description: 'Gheymat - AI-Powered Currency Predictions for Smarter Investment Decisions'
        },
        nav: {
            home: 'Home',
            ios: 'App Store',
            android: 'Google Play',
            contact: 'Contact',
            download: 'Download App',
            login: 'Sign In',
            register: 'Get Started',
            logout: 'Sign Out',
            tierPremium: '★ Premium',
            tierFree: 'Free'
        },
        auth: {
            loginTab: 'Sign In',
            registerTab: 'Create Account',
            loginTitle: 'Welcome back',
            registerTitle: 'Create your account',
            email: 'Email',
            password: 'Password',
            name: 'Full Name',
            loginBtn: 'Sign In',
            registerBtn: 'Create Account',
            freeNote: 'Free account — upgrade to Premium anytime.'
        },
        predictions: {
            title: 'AI Currency Predictions',
            subtitle: '7-day forecasts powered by machine learning',
            loading: 'Loading predictions...',
            error: 'Failed to load predictions.',
            aiPowered: 'AI Powered',
            currentPrice: 'Current',
            predicted: 'Predicted (7d)',
            confidence: 'Confidence',
            trend: 'Trend',
            lockTitle: 'Premium Feature',
            lockDesc: 'Get AI-powered 7-day forecasts for all currencies. Sign in and upgrade to Premium.',
            unlock: 'Unlock Predictions',
            upgradePrompt: 'Upgrade to Premium',
            up: '↑ Up',
            down: '↓ Down',
            neutral: '→ Neutral'
        },
        hero: {
            title: 'Currency Predictions',
            description: 'AI-powered forecasts for Iranian exchange rates',
            downloadFrom: 'Download from'
        },
        prices: {
            title: 'Latest Rates',
            subtitle: 'Prices in Toman',
            live: 'Live',
            loading: 'Loading latest prices...',
            error: 'Failed to load prices. Please try again later.',
            viewAll: 'View All Rates',
            buy: 'Buy',
            sell: 'Sell',
            dashboard: 'Open Dashboard',
            retry: 'Retry',
            toman: 'Toman',
            loadError: 'Failed to load prices. Please try again.'
        },
        pricesPage: {
            title: 'All Currency Prices',
            subtitle: 'Real-time exchange rates for all available currencies',
            backButton: 'Back to Home'
        },
        currencyModal: {
            gateTitle: 'Premium Charts & AI Analysis',
            gateDesc: 'Upgrade to Premium to unlock full price charts, historical data, and live AI predictions for every currency.',
            gateBtn: 'Upgrade to Premium',
            chartLabel: '7-Day Price History',
            aiTitle: 'AI Prediction · 7 Days',
            aiLoading: 'Running AI model…',
            aiError: 'Prediction unavailable',
            predicted: 'Predicted Price',
            confidence: 'Confidence',
            trend: 'Trend',
            buy: 'Buy',
            sell: 'Sell',
            high: 'High',
            low: 'Low'
        },
        footer: {
            copyright: '© 2025 Gheymat. All rights reserved.'
        },
        currencies: {
            usd: 'US Dollar',
            eur: 'Euro',
            gbp: 'British Pound',
            try: 'Turkish Lira',
            aed: 'UAE Dirham',
            cny: 'Chinese Yuan',
            jpy: 'Japanese Yen',
            cad: 'Canadian Dollar',
            aud: 'Australian Dollar',
            chf: 'Swiss Franc',
            rub: 'Russian Ruble',
            inr: 'Indian Rupee',
            krw: 'South Korean Won',
            sek: 'Swedish Krona',
            nok: 'Norwegian Krone',
            dkk: 'Danish Krone',
            sgd: 'Singapore Dollar',
            hkd: 'Hong Kong Dollar',
            nzd: 'New Zealand Dollar',
            mxn: 'Mexican Peso',
            brl: 'Brazilian Real',
            zar: 'South African Rand',
            thb: 'Thai Baht',
            pln: 'Polish Zloty',
            czk: 'Czech Koruna',
            huf: 'Hungarian Forint',
            ron: 'Romanian Leu',
            ils: 'Israeli Shekel',
            php: 'Philippine Peso',
            myr: 'Malaysian Ringgit',
            idr: 'Indonesian Rupiah',
            clp: 'Chilean Peso',
            cop: 'Colombian Peso',
            ars: 'Argentine Peso',
            iqd: 'Iraqi Dinar',
            sar: 'Saudi Riyal',
            kwd: 'Kuwaiti Dinar',
            qar: 'Qatari Riyal',
            omr: 'Omani Rial',
            bhd: 'Bahraini Dinar',
            azn: 'Azerbaijani Manat',
            gel: 'Georgian Lari',
            amd: 'Armenian Dram',
            afn: 'Afghan Afghani'
        }
    },
    fa: {
        meta: {
            title: 'قیمت - پیش‌بینی قیمت ارز با هوش مصنوعی',
            description: 'قیمت - پیش‌بینی قیمت ارز با هوش مصنوعی برای تصمیمات سرمایه‌گذاری هوشمندانه'
        },
        nav: {
            home: 'خانه',
            ios: 'اپ استور',
            android: 'گوگل پلی',
            contact: 'تماس با ما',
            download: 'دانلود اپلیکیشن',
            login: 'ورود',
            register: 'ثبت‌نام',
            logout: 'خروج',
            tierPremium: '★ پریمیوم',
            tierFree: 'رایگان'
        },
        auth: {
            loginTab: 'ورود',
            registerTab: 'ایجاد حساب',
            loginTitle: 'خوش برگشتید',
            registerTitle: 'ایجاد حساب کاربری',
            email: 'ایمیل',
            password: 'رمز عبور',
            name: 'نام کامل',
            loginBtn: 'ورود',
            registerBtn: 'ایجاد حساب',
            freeNote: 'حساب رایگان — هر زمان به پریمیوم ارتقا دهید.'
        },
        predictions: {
            title: 'پیش‌بینی قیمت ارز با هوش مصنوعی',
            subtitle: 'پیش‌بینی ۷ روزه با یادگیری ماشین',
            loading: 'در حال بارگذاری...',
            error: 'خطا در بارگذاری پیش‌بینی‌ها.',
            aiPowered: 'هوش مصنوعی',
            currentPrice: 'فعلی',
            predicted: 'پیش‌بینی (۷ روز)',
            confidence: 'اطمینان',
            trend: 'روند',
            lockTitle: 'ویژگی پریمیوم',
            lockDesc: 'پیش‌بینی ۷ روزه با هوش مصنوعی. وارد شوید و به پریمیوم ارتقا دهید.',
            unlock: 'باز کردن پیش‌بینی‌ها',
            upgradePrompt: 'ارتقا به پریمیوم',
            up: '↑ صعودی',
            down: '↓ نزولی',
            neutral: '→ خنثی'
        },
        hero: {
            title: 'پیش‌بینی قیمت ارز',
            description: 'پیش‌بینی پیشرفته نرخ ارز با استفاده از هوش مصنوعی',
            downloadFrom: 'دانلود از'
        },
        prices: {
            title: 'آخرین نرخ‌ها',
            subtitle: 'قیمت به تومان',
            live: 'زنده',
            loading: 'در حال بارگذاری قیمت‌ها...',
            error: 'خطا در بارگذاری قیمت‌ها. لطفا دوباره تلاش کنید.',
            viewAll: 'همه نرخ‌ها',
            buy: 'خرید',
            sell: 'فروش',
            dashboard: 'باز کردن داشبورد',
            retry: 'تلاش مجدد',
            toman: 'تومان',
            loadError: 'خطا در بارگذاری قیمت‌ها. لطفاً دوباره تلاش کنید.'
        },
        pricesPage: {
            title: 'همه قیمت‌های ارز',
            subtitle: 'نرخ ارز به‌روز برای همه ارزهای موجود',
            backButton: 'بازگشت به خانه'
        },
        currencyModal: {
            gateTitle: 'نمودار و تحلیل هوش مصنوعی',
            gateDesc: 'برای دسترسی به نمودار کامل، داده‌های تاریخی و پیش‌بینی زنده هوش مصنوعی برای هر ارز، به پریمیوم ارتقا دهید.',
            gateBtn: 'ارتقا به پریمیوم',
            chartLabel: 'تاریخچه ۷ روز گذشته',
            aiTitle: 'پیش‌بینی هوش مصنوعی · ۷ روز',
            aiLoading: 'در حال اجرای مدل هوش مصنوعی…',
            aiError: 'پیش‌بینی در دسترس نیست',
            predicted: 'قیمت پیش‌بینی‌شده',
            confidence: 'اطمینان',
            trend: 'روند',
            buy: 'خرید',
            sell: 'فروش',
            high: 'بالا',
            low: 'پایین'
        },
        footer: {
            copyright: '© ۲۰۲۵ قیمت. تمامی حقوق محفوظ است.'
        },
        currencies: {
            usd: 'دلار آمریکا',
            eur: 'یورو',
            gbp: 'پوند انگلیس',
            try: 'لیر ترکیه',
            aed: 'درهم امارات',
            cny: 'یوان چین',
            jpy: 'ین ژاپن',
            cad: 'دلار کانادا',
            aud: 'دلار استرالیا',
            chf: 'فرانک سوئیس',
            rub: 'روبل روسیه',
            inr: 'روپیه هند',
            krw: 'وون کره جنوبی',
            sek: 'کرون سوئد',
            nok: 'کرون نروژ',
            dkk: 'کرون دانمارک',
            sgd: 'دلار سنگاپور',
            hkd: 'دلار هنگ کنگ',
            nzd: 'دلار نیوزیلند',
            mxn: 'پزو مکزیک',
            brl: 'رئال برزیل',
            zar: 'راند آفریقای جنوبی',
            thb: 'بات تایلند',
            pln: 'زلوتی لهستان',
            czk: 'کرون جمهوری چک',
            huf: 'فورینت مجارستان',
            ron: 'لئو رومانی',
            ils: 'شکل اسرائیل',
            php: 'پزو فیلیپین',
            myr: 'رینگیت مالزی',
            idr: 'روپیه اندونزی',
            clp: 'پزو شیلی',
            cop: 'پزو کلمبیا',
            ars: 'پزو آرژانتین',
            iqd: 'دینار عراق',
            sar: 'ریال عربستان',
            kwd: 'دینار کویت',
            qar: 'ریال قطر',
            omr: 'ریال عمان',
            bhd: 'دینار بحرین',
            azn: 'منات آذربایجان',
            gel: 'لاری گرجستان',
            amd: 'درام ارمنستان',
            afn: 'افغانی افغانستان'
        }
    }
};

let currentLang = localStorage.getItem('lang') || 'en';
let currentTheme = localStorage.getItem('theme') || 'dark';

// Apply saved preferences
document.documentElement.setAttribute('data-theme', currentTheme);
document.documentElement.setAttribute('dir', currentLang === 'fa' ? 'rtl' : 'ltr');
document.documentElement.setAttribute('lang', currentLang);

// ==========================================
// Language & Theme Management
// ==========================================

function updateLanguage(lang) {
    currentLang = lang;
    localStorage.setItem('lang', lang);
    document.documentElement.setAttribute('dir', lang === 'fa' ? 'rtl' : 'ltr');
    document.documentElement.setAttribute('lang', lang);

    // Update page metadata
    document.title = translations[lang].meta.title;
    const metaDescription = document.querySelector('meta[name="description"]');
    if (metaDescription) {
        metaDescription.setAttribute('content', translations[lang].meta.description);
    }

    // Update all i18n elements
    document.querySelectorAll('[data-i18n]').forEach(element => {
        const key = element.getAttribute('data-i18n');
        const keys = key.split('.');
        let value = translations[lang];

        for (const k of keys) {
            value = value?.[k];
        }

        if (value) {
            element.textContent = value;
        }
    });

    // Update language toggle
    const langToggle = document.querySelector('.lang-text');
    if (langToggle) {
        langToggle.textContent = lang === 'en' ? 'فا' : 'EN';
    }

    // Refresh data and nav
    if (typeof updateNavAuth === 'function') updateNavAuth();
    if (typeof updatePrices === 'function') updatePrices();
}

function updateTheme(theme) {
    currentTheme = theme;
    localStorage.setItem('theme', theme);
    document.documentElement.setAttribute('data-theme', theme);

    // Update aria-pressed state
    const themeToggle = document.getElementById('themeToggle');
    if (themeToggle) {
        themeToggle.setAttribute('aria-pressed', theme === 'light' ? 'true' : 'false');
    }
}

// ==========================================
// Enhanced Neural Network Animation
// ==========================================

class NeuralNetwork {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.nodes = [];
        this.particles = [];
        this.nodeCount = 60;
        this.maxDistance = 180;
        this.mouse = { x: null, y: null, radius: 250 };
        this.time = 0;
        this.hubs = [];

        this.resize();
        this.init();
        this.animate();

        window.addEventListener('resize', () => this.resize());

        // Mouse tracking
        window.addEventListener('mousemove', (e) => {
            this.mouse.x = e.clientX;
            this.mouse.y = e.clientY;
        });

        window.addEventListener('mouseleave', () => {
            this.mouse.x = null;
            this.mouse.y = null;
        });
    }

    resize() {
        this.canvas.width = window.innerWidth;
        this.canvas.height = window.innerHeight;
        this.init();
    }

    init() {
        this.nodes = [];
        this.particles = [];
        this.hubs = [];

        // Create hub nodes (larger connection points)
        const hubCount = 5;
        for (let i = 0; i < hubCount; i++) {
            this.hubs.push({
                x: Math.random() * this.canvas.width,
                y: Math.random() * this.canvas.height,
                vx: (Math.random() - 0.5) * 0.2,
                vy: (Math.random() - 0.5) * 0.2,
                radius: 3,
                pulsePhase: Math.random() * Math.PI * 2,
                isHub: true
            });
        }

        // Create regular nodes with varied properties
        for (let i = 0; i < this.nodeCount; i++) {
            this.nodes.push({
                x: Math.random() * this.canvas.width,
                y: Math.random() * this.canvas.height,
                baseX: Math.random() * this.canvas.width,
                baseY: Math.random() * this.canvas.height,
                vx: (Math.random() - 0.5) * 0.4,
                vy: (Math.random() - 0.5) * 0.4,
                radius: Math.random() * 2 + 1,
                pulsePhase: Math.random() * Math.PI * 2,
                pulseSpeed: Math.random() * 0.02 + 0.01,
                isHub: false
            });
        }

        // Combine hubs and nodes
        this.allNodes = [...this.hubs, ...this.nodes];
    }

    createParticle(x1, y1, x2, y2) {
        this.particles.push({
            x: x1,
            y: y1,
            targetX: x2,
            targetY: y2,
            progress: 0,
            speed: 0.02 + Math.random() * 0.03,
            life: 1
        });
    }

    animate() {
        this.time += 0.01;

        // Clear canvas with gradient background - respect theme
        const gradient = this.ctx.createRadialGradient(
            this.canvas.width / 2, this.canvas.height / 2, 0,
            this.canvas.width / 2, this.canvas.height / 2, this.canvas.width / 1.5
        );

        // Check current theme and apply appropriate colors
        const isLightTheme = document.documentElement.getAttribute('data-theme') === 'light';
        if (isLightTheme) {
            gradient.addColorStop(0, 'rgba(255, 255, 255, 1)');
            gradient.addColorStop(1, 'rgba(250, 250, 250, 1)');
        } else {
            gradient.addColorStop(0, 'rgba(9, 9, 13, 1)');
            gradient.addColorStop(1, 'rgba(0, 0, 0, 1)');
        }

        this.ctx.fillStyle = gradient;
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

        // Update particles with glow
        this.particles = this.particles.filter(particle => {
            particle.progress += particle.speed;
            particle.life = 1 - particle.progress;

            if (particle.progress >= 1) return false;

            const x = particle.x + (particle.targetX - particle.x) * particle.progress;
            const y = particle.y + (particle.targetY - particle.y) * particle.progress;

            // Draw particle with glow - adjust color for theme
            const isLightTheme = document.documentElement.getAttribute('data-theme') === 'light';
            const particleColor = isLightTheme ? '0, 0, 0' : '255, 255, 255';

            const particleGradient = this.ctx.createRadialGradient(x, y, 0, x, y, 3);
            particleGradient.addColorStop(0, `rgba(${particleColor}, ${particle.life * 0.8})`);
            particleGradient.addColorStop(1, `rgba(${particleColor}, 0)`);

            this.ctx.beginPath();
            this.ctx.arc(x, y, 3, 0, Math.PI * 2);
            this.ctx.fillStyle = particleGradient;
            this.ctx.fill();

            return true;
        });

        // Update and draw all nodes
        this.allNodes.forEach((node, i) => {
            // Mouse interaction
            if (this.mouse.x !== null) {
                const dx = this.mouse.x - node.x;
                const dy = this.mouse.y - node.y;
                const distance = Math.sqrt(dx * dx + dy * dy);

                if (distance < this.mouse.radius) {
                    const force = (this.mouse.radius - distance) / this.mouse.radius;
                    const angle = Math.atan2(dy, dx);
                    node.x -= Math.cos(angle) * force * 3;
                    node.y -= Math.sin(angle) * force * 3;
                }
            }

            // Move nodes
            node.x += node.vx;
            node.y += node.vy;

            // Bounce off edges with padding
            const padding = 50;
            if (node.x < -padding) node.x = this.canvas.width + padding;
            if (node.x > this.canvas.width + padding) node.x = -padding;
            if (node.y < -padding) node.y = this.canvas.height + padding;
            if (node.y > this.canvas.height + padding) node.y = -padding;

            // Enhanced pulsing effect
            const pulse = Math.sin(this.time * (node.pulseSpeed || 0.01) + node.pulsePhase) * 0.5 + 0.5;
            const currentRadius = node.radius * (0.7 + pulse * 0.3);
            const nodeOpacity = node.isHub ? 0.6 : 0.4;

            // Draw node with glow - adjust colors for theme
            const isLightTheme = document.documentElement.getAttribute('data-theme') === 'light';
            const nodeColor = isLightTheme ? '0, 0, 0' : '255, 255, 255';

            const nodeGradient = this.ctx.createRadialGradient(
                node.x, node.y, 0,
                node.x, node.y, currentRadius * 2
            );
            nodeGradient.addColorStop(0, `rgba(${nodeColor}, ${nodeOpacity + pulse * 0.2})`);
            nodeGradient.addColorStop(0.5, `rgba(${nodeColor}, ${(nodeOpacity + pulse * 0.2) * 0.3})`);
            nodeGradient.addColorStop(1, `rgba(${nodeColor}, 0)`);

            this.ctx.beginPath();
            this.ctx.arc(node.x, node.y, currentRadius * 2, 0, Math.PI * 2);
            this.ctx.fillStyle = nodeGradient;
            this.ctx.fill();

            // Draw connections
            for (let j = i + 1; j < this.allNodes.length; j++) {
                const dx = this.allNodes[j].x - node.x;
                const dy = this.allNodes[j].y - node.y;
                const distance = Math.sqrt(dx * dx + dy * dy);

                if (distance < this.maxDistance) {
                    const opacity = (1 - distance / this.maxDistance) * 0.2;
                    const lineWidth = node.isHub || this.allNodes[j].isHub ? 1 : 0.5;

                    // Draw connection line - adjust color for theme
                    const isLightTheme = document.documentElement.getAttribute('data-theme') === 'light';
                    const lineColor = isLightTheme ? '0, 0, 0' : '255, 255, 255';

                    this.ctx.beginPath();
                    this.ctx.moveTo(node.x, node.y);
                    this.ctx.lineTo(this.allNodes[j].x, this.allNodes[j].y);
                    this.ctx.strokeStyle = `rgba(${lineColor}, ${opacity})`;
                    this.ctx.lineWidth = lineWidth;
                    this.ctx.stroke();

                    // Create particles along strong connections
                    if (opacity > 0.12 && Math.random() < 0.005) {
                        this.createParticle(node.x, node.y, this.allNodes[j].x, this.allNodes[j].y);
                    }
                }
            }
        });

        requestAnimationFrame(() => this.animate());
    }
}

// ==========================================
// Currency Data API
// ==========================================

const _isGitHubPages = window.location.hostname.includes('github.io');
const API_URL = _isGitHubPages
    ? 'https://linx64.github.io/CurrencyCapPortal/api/latest.json'
    : '/api/latest';
const AUTH_API_URL = window.AUTH_API_URL || (_isGitHubPages ? 'https://gheymat-api-production.up.railway.app' : '');
const FEATURED_CURRENCIES = ['usd', 'eur', 'gbp', 'try', 'aed', 'cny', 'cad', 'aud', 'rub', 'jpy', 'chf', 'sar'];
const PREDICTION_CURRENCIES = ['usd', 'eur', 'gbp', 'try', 'aed', 'cny'];

// ==========================================
// Auth State
// ==========================================

const auth = {
    get token() { return localStorage.getItem('gheymat_token'); },
    get refreshToken() { return localStorage.getItem('gheymat_refresh'); },
    get user() {
        try { return JSON.parse(localStorage.getItem('gheymat_user') || 'null'); } catch { return null; }
    },
    save(data) {
        localStorage.setItem('gheymat_token', data.access_token);
        if (data.refresh_token) localStorage.setItem('gheymat_refresh', data.refresh_token);
        localStorage.setItem('gheymat_user', JSON.stringify(data.user));
    },
    clear() {
        localStorage.removeItem('gheymat_token');
        localStorage.removeItem('gheymat_refresh');
        localStorage.removeItem('gheymat_user');
    },
    isPremium() { return this.user?.tier === 'premium'; },
    isLoggedIn() { return !!this.token && !!this.user; }
};

async function authFetch(path, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (auth.token) headers['Authorization'] = `Bearer ${auth.token}`;
    const res = await fetch(`${AUTH_API_URL}${path}`, { ...options, headers });
    return res;
}

function updateNavAuth() {
    const navAuth = document.getElementById('navAuth');
    const navUser = document.getElementById('navUser');
    const navUserName = document.getElementById('navUserName');
    const navUserTier = document.getElementById('navUserTier');
    if (!navAuth || !navUser) return;

    if (auth.isLoggedIn()) {
        navAuth.style.display = 'none';
        navUser.style.display = 'flex';
        if (navUserName) navUserName.textContent = auth.user.name || auth.user.email;
        if (navUserTier) {
            const tn = translations[currentLang].nav;
            navUserTier.textContent = auth.isPremium() ? tn.tierPremium : tn.tierFree;
            navUserTier.className = 'nav-user-tier' + (auth.isPremium() ? ' premium' : '');
        }
    } else {
        navAuth.style.display = 'flex';
        navUser.style.display = 'none';
    }
    updatePredictionsGate();
}

function updatePredictionsGate() {
    const gate = document.getElementById('predictionsGate');
    const grid = document.getElementById('predictionsGrid');
    if (!gate || !grid) return;

    if (auth.isLoggedIn() && auth.isPremium()) {
        gate.style.display = 'none';
        grid.style.display = 'grid';
        loadPredictions();
    } else {
        gate.style.display = 'block';
        grid.style.display = 'none';
    }
}

// Store previous prices to calculate change
let previousPrices = {};

async function fetchLatestPrices() {
    try {
        // Fetch with no caching to always get fresh data
        const response = await fetch(`${API_URL}?t=${Date.now()}`, {
            cache: 'no-store'
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        console.log('✅ Fresh prices fetched from API');
        return data;
    } catch (error) {
        console.error('❌ Error fetching prices:', error);
        return null;
    }
}

// ==========================================
// Utility Functions
// ==========================================

function formatPrice(price) {
    return new Intl.NumberFormat('en-US', {
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
    }).format(price);
}

function getLatestPrice(currency) {
    if (!currency.ps || currency.ps.length === 0) {
        return null;
    }
    // Get the most recent price from the array
    const latestPriceData = currency.ps[currency.ps.length - 1];
    return latestPriceData.sp || latestPriceData.bp || 0;
}

function calculatePriceChange(currencyCode, currentPrice) {
    if (!previousPrices[currencyCode] || currentPrice === 0) {
        return 0;
    }

    const previousPrice = previousPrices[currencyCode];
    const change = ((currentPrice - previousPrice) / previousPrice) * 100;
    return parseFloat(change.toFixed(2));
}


// ==========================================
// Price Card Creation
// ==========================================

function createPriceCard(currency) {
    const latestPs = currency.ps?.[currency.ps.length - 1];
    if (!latestPs) return '';

    const buyPrice = latestPs.bp || 0;
    const sellPrice = latestPs.sp || 0;
    const price = sellPrice || buyPrice;
    if (!price) return '';

    const currencyCode = currency.ab.toLowerCase();
    const change = calculatePriceChange(currencyCode, price);
    const isPositive = change >= 0;
    previousPrices[currencyCode] = price;

    const currencyName = translations[currentLang].currencies[currencyCode] || currency.en;
    const t = translations[currentLang];
    const buyLabel  = t.prices?.buy  || 'Buy';
    const sellLabel = t.prices?.sell || 'Sell';

    return `
        <div class="price-item" data-currency="${currency.ab}" role="listitem" tabindex="0"
             aria-label="${currencyName}: ${formatPrice(sellPrice)} ${translations[currentLang].prices.toman}">
            <div class="price-item-header">
                <div class="price-info">
                    <div class="currency-flag" aria-hidden="true">${currency.av || currency.ab.charAt(0).toUpperCase()}</div>
                    <div class="currency-details">
                        <span class="currency-code">${currency.ab.toUpperCase()}</span>
                        <span class="currency-name">${currencyName}</span>
                    </div>
                </div>
                ${change !== 0 ? `<span class="price-change ${isPositive ? 'positive' : 'negative'}">${isPositive ? '+' : ''}${change}%</span>` : ''}
            </div>
            <div class="price-buysell">
                <div class="price-side">
                    <span class="price-side-label">${buyLabel}</span>
                    <span class="price-amount">${formatPrice(buyPrice)}</span>
                </div>
                <div class="price-side-divider"></div>
                <div class="price-side">
                    <span class="price-side-label">${sellLabel}</span>
                    <span class="price-amount">${formatPrice(sellPrice)}</span>
                </div>
            </div>
        </div>
    `;
}

// ==========================================
// Update Prices
// ==========================================

function createSkeletonCard() {
    return `
        <div class="skeleton-card">
            <div class="skeleton-header">
                <div class="skeleton skeleton-icon"></div>
                <div class="skeleton-text">
                    <div class="skeleton skeleton-line"></div>
                    <div class="skeleton skeleton-line short"></div>
                </div>
            </div>
            <div>
                <div class="skeleton skeleton-price"></div>
                <div class="skeleton skeleton-change"></div>
            </div>
        </div>
    `;
}

async function updatePrices() {
    const pricesGrid = document.querySelector('.prices-grid');
    if (!pricesGrid) {
        console.warn('Prices grid not found');
        return;
    }

    // Show loading state
    const liveIndicator = document.querySelector('.live-indicator');
    if (liveIndicator) {
        liveIndicator.classList.add('refreshing');
    }
    pricesGrid.innerHTML = Array(8).fill(createSkeletonCard()).join('');

    // Fetch fresh data from API (no cache)
    const data = await fetchLatestPrices();
    if (Array.isArray(data)) _lastPrices = data;

    // Remove loading state
    if (liveIndicator) {
        liveIndicator.classList.remove('refreshing');
    }

    // Handle error
    if (!data || !Array.isArray(data)) {
        console.error('Invalid data received from API');
        pricesGrid.innerHTML = `
            <div class="state-message">
                <div class="state-icon error">
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"></circle>
                        <line x1="12" y1="8" x2="12" y2="12"></line>
                        <line x1="12" y1="16" x2="12.01" y2="16"></line>
                    </svg>
                </div>
                <h3 class="state-title">${translations[currentLang].prices.error}</h3>
                <p class="state-description">${translations[currentLang].prices.loadError}</p>
                <button class="retry-btn" onclick="updatePrices()">${translations[currentLang].prices.retry}</button>
            </div>
        `;
        return;
    }

    // Filter and sort currencies
    const currencies = data
        .filter(item => item.ty === 'cu' && FEATURED_CURRENCIES.includes(item.ab))
        .sort((a, b) => FEATURED_CURRENCIES.indexOf(a.ab) - FEATURED_CURRENCIES.indexOf(b.ab));

    console.log(`📊 Displaying ${currencies.length} currencies`);

    // Create price cards
    const html = currencies.map(currency => createPriceCard(currency)).join('');

    if (html) {
        pricesGrid.innerHTML = html;
        initCardClicks();
    } else {
        console.error('No price cards generated');
    }

    // Add / refresh "View All" footer link
    const container = pricesGrid.closest('.prices-container');
    if (container) {
        let footer = container.querySelector('.prices-footer');
        if (!footer) {
            footer = document.createElement('div');
            footer.className = 'prices-footer';
            container.appendChild(footer);
        }
        const t = translations[currentLang].prices;
        footer.innerHTML = `
            <a href="dashboard.html" class="prices-view-all">
                ${t.dashboard}
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"></polyline></svg>
            </a>
            <a href="prices.html" class="prices-view-all prices-view-all--ghost">
                ${t.viewAll}
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"></polyline></svg>
            </a>
        `;
    }
}

// ==========================================
// Mouse Tracking for Cards
// ==========================================

function initMouseTracking() {
    document.addEventListener('mousemove', (e) => {
        document.querySelectorAll('.price-item, .prediction-card').forEach(card => {
            const rect = card.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;

            card.style.setProperty('--mouse-x', `${x}px`);
            card.style.setProperty('--mouse-y', `${y}px`);
        });
    });
}

// ==========================================
// Scroll to Top Functionality
// ==========================================

function initScrollToTop() {
    const scrollBtn = document.getElementById('scrollToTop');
    if (!scrollBtn) return;

    // Show/hide button based on scroll position
    window.addEventListener('scroll', () => {
        if (window.scrollY > 300) {
            scrollBtn.classList.add('visible');
        } else {
            scrollBtn.classList.remove('visible');
        }
    });

    // Scroll to top when clicked
    scrollBtn.addEventListener('click', () => {
        window.scrollTo({
            top: 0,
            behavior: 'smooth'
        });
    });
}

// ==========================================
// Sticky Navbar Functionality
// ==========================================

function initStickyNavbar() {
    const navbar = document.querySelector('.navbar');
    if (!navbar) return;

    window.addEventListener('scroll', () => {
        if (window.scrollY > 50) {
            navbar.classList.add('scrolled');
        } else {
            navbar.classList.remove('scrolled');
        }
    });
}

// ==========================================
// Initialize Everything
// ==========================================

document.addEventListener('DOMContentLoaded', () => {
    // Initialize language
    updateLanguage(currentLang);

    // Language toggle
    const langToggle = document.getElementById('langToggle');
    if (langToggle) {
        langToggle.addEventListener('click', () => {
            const newLang = currentLang === 'en' ? 'fa' : 'en';
            updateLanguage(newLang);
        });
    }

    // Theme toggle
    const themeToggle = document.getElementById('themeToggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', () => {
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            updateTheme(newTheme);
        });
    }

    // Initialize Neural Network
    const neuralCanvas = document.getElementById('neuralBackground');
    if (neuralCanvas) {
        new NeuralNetwork(neuralCanvas);
    }

    // Initialize prices
    updatePrices();

    // Initialize auth
    initAuthModal();
    updateNavAuth();

    // Mouse tracking
    initMouseTracking();

    // Scroll to top button
    initScrollToTop();

    // Sticky navbar
    initStickyNavbar();

    // Smooth fade in
    document.body.style.opacity = '0';
    document.body.style.transition = 'opacity 0.5s ease';
    setTimeout(() => {
        document.body.style.opacity = '1';
    }, 100);
});

// Auto-refresh prices every 30 seconds
setInterval(() => updatePrices(), 30000);

// ==========================================
// Auth Modal
// ==========================================

function openAuthModal(tab = 'login') {
    const modal = document.getElementById('authModal');
    if (modal) {
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
        switchAuthTab(tab);
    }
}

function closeAuthModal() {
    const modal = document.getElementById('authModal');
    if (modal) {
        modal.style.display = 'none';
        document.body.style.overflow = '';
    }
}

function switchAuthTab(tab) {
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');
    const tabLogin = document.getElementById('tabLogin');
    const tabRegister = document.getElementById('tabRegister');
    if (!loginForm || !registerForm) return;

    if (tab === 'login') {
        loginForm.style.display = 'block';
        registerForm.style.display = 'none';
        tabLogin.classList.add('active');
        tabRegister.classList.remove('active');
    } else {
        loginForm.style.display = 'none';
        registerForm.style.display = 'block';
        tabLogin.classList.remove('active');
        tabRegister.classList.add('active');
    }
}

function initAuthModal() {
    document.getElementById('modalClose')?.addEventListener('click', closeAuthModal);
    document.getElementById('authModal')?.addEventListener('click', (e) => {
        if (e.target.id === 'authModal') closeAuthModal();
    });
    document.getElementById('tabLogin')?.addEventListener('click', () => switchAuthTab('login'));
    document.getElementById('tabRegister')?.addEventListener('click', () => switchAuthTab('register'));

    document.getElementById('navLoginBtn')?.addEventListener('click', () => openAuthModal('login'));
    document.getElementById('navRegisterBtn')?.addEventListener('click', () => openAuthModal('register'));
    document.getElementById('unlockPredictionsBtn')?.addEventListener('click', () => {
        if (auth.isLoggedIn()) openAuthModal('upgrade');
        else openAuthModal('register');
    });

    document.getElementById('navLogoutBtn')?.addEventListener('click', () => {
        auth.clear();
        updateNavAuth();
    });

    // Login form submit
    document.getElementById('loginForm')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('loginEmail').value;
        const password = document.getElementById('loginPassword').value;
        const errEl = document.getElementById('loginError');
        const btn = document.getElementById('loginSubmit');
        errEl.textContent = '';
        btn.disabled = true;
        btn.textContent = '...';

        try {
            const res = await authFetch('/api/auth/login', {
                method: 'POST',
                body: JSON.stringify({ email, password })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Login failed');
            auth.save(data);
            closeAuthModal();
            updateNavAuth();
        } catch (err) {
            errEl.textContent = err.message;
        } finally {
            btn.disabled = false;
            btn.textContent = translations[currentLang].auth.loginBtn;
        }
    });

    // Register form submit
    document.getElementById('registerForm')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = document.getElementById('regName').value;
        const email = document.getElementById('regEmail').value;
        const password = document.getElementById('regPassword').value;
        const errEl = document.getElementById('registerError');
        const btn = document.getElementById('registerSubmit');
        errEl.textContent = '';
        btn.disabled = true;
        btn.textContent = '...';

        try {
            const res = await authFetch('/api/auth/register', {
                method: 'POST',
                body: JSON.stringify({ name, email, password })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Registration failed');
            auth.save(data);
            closeAuthModal();
            updateNavAuth();
        } catch (err) {
            errEl.textContent = err.message;
        } finally {
            btn.disabled = false;
            btn.textContent = translations[currentLang].auth.registerBtn;
        }
    });
}

// ==========================================
// AI Predictions (Premium)
// ==========================================

async function loadPredictions() {
    const grid = document.getElementById('predictionsGrid');
    if (!grid) return;

    grid.innerHTML = '<div class="predictions-loading" data-i18n="predictions.loading">Loading predictions...</div>';

    const t = translations[currentLang].predictions;

    try {
        const results = await Promise.allSettled(
            PREDICTION_CURRENCIES.map(code =>
                authFetch('/api/v1/predict', {
                    method: 'POST',
                    body: JSON.stringify({ currencyCode: code, daysAhead: 7, useML: true })
                }).then(r => r.json().then(d => ({ code, data: d, ok: r.ok })))
            )
        );

        const cards = results
            .filter(r => r.status === 'fulfilled' && r.value.ok)
            .map(r => {
                const { code, data } = r.value;
                const pred = data.predictions?.[0] || {};
                const currentPrice = data.currentPrice?.sell || data.currentPrice?.buy || 0;
                const predictedPrice = pred.price || 0;
                const pctChange = currentPrice > 0
                    ? (((predictedPrice - currentPrice) / currentPrice) * 100).toFixed(1)
                    : '0.0';
                const isUp = parseFloat(pctChange) > 0;
                const isDown = parseFloat(pctChange) < 0;
                const confidence = pred.confidence ? (pred.confidence * 100).toFixed(0) : '--';
                const trend = pred.trend || 'neutral';
                const trendLabel = trend === 'up' ? t.up : trend === 'down' ? t.down : t.neutral;
                const currencyName = translations[currentLang].currencies[code] || code.toUpperCase();
                const flag = data.flag || '';

                return `
                    <div class="prediction-card" role="listitem">
                        <div class="pred-header">
                            <div class="pred-currency">
                                <span class="pred-flag">${flag}</span>
                                <div>
                                    <span class="pred-code">${code.toUpperCase()}</span>
                                    <span class="pred-name">${currencyName}</span>
                                </div>
                            </div>
                            <div class="pred-trend ${trend}">${trendLabel}</div>
                        </div>
                        <div class="pred-prices">
                            <div class="pred-price-item">
                                <span class="pred-label">${t.currentPrice}</span>
                                <span class="pred-value">${formatPrice(currentPrice)}</span>
                            </div>
                            <div class="pred-price-item">
                                <span class="pred-label">${t.predicted}</span>
                                <span class="pred-value ${isUp ? 'positive' : isDown ? 'negative' : ''}">${formatPrice(predictedPrice)}</span>
                            </div>
                        </div>
                        <div class="pred-footer">
                            <span class="pred-confidence">${t.confidence}: ${confidence}%</span>
                            <span class="pred-change ${isUp ? 'positive' : isDown ? 'negative' : ''}">${isUp ? '+' : ''}${pctChange}%</span>
                        </div>
                    </div>`;
            }).join('');

        grid.innerHTML = cards || `<p class="predictions-error">${t.error}</p>`;
    } catch (err) {
        grid.innerHTML = `<p class="predictions-error">${t.error}</p>`;
    }
}

// ==========================================
// Currency Detail Modal
// ==========================================

// Cache for history data to avoid refetching per session
const _historyCache = {};

function _drawSparkChart(points, isUp) {
    if (!points || points.length < 2) return '';
    const W = 460, H = 110;
    const min = Math.min(...points);
    const max = Math.max(...points);
    const range = max - min || 1;
    const pad = 10;
    const xs = points.map((_, i) => pad + (i / (points.length - 1)) * (W - pad * 2));
    const ys = points.map(p => H - pad - ((p - min) / range) * (H - pad * 2));
    const line = xs.map((x, i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(' ');
    const area = `${line} L${xs[xs.length - 1].toFixed(1)},${H} L${xs[0].toFixed(1)},${H} Z`;
    const color = isUp ? '#10B981' : '#EF4444';
    const gid = `cg${Date.now()}`;
    return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" width="100%" height="100%">
        <defs>
            <linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="${color}" stop-opacity="0.25"/>
                <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
            </linearGradient>
        </defs>
        <path d="${area}" fill="url(#${gid})"/>
        <path d="${line}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>
    </svg>`;
}

function _renderCurrencyGate(currency) {
    const t = translations[currentLang].currencyModal;
    const name = translations[currentLang].currencies[currency.ab.toLowerCase()] || currency.en;
    return `
        <div class="cmodal-gate">
            <div class="cmodal-gate-icon">
                <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                    <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
                </svg>
            </div>
            <div style="font-size:2rem">${currency.av || ''}</div>
            <div class="cmodal-code" id="cmodalTitle">${currency.ab.toUpperCase()} — ${name}</div>
            <div class="cmodal-gate-title">${t.gateTitle}</div>
            <p class="cmodal-gate-desc">${t.gateDesc}</p>
            <button class="cmodal-gate-btn" id="cmodalUpgradeBtn">${t.gateBtn}</button>
        </div>`;
}

function _renderCurrencyContent(currency, historyPoints, t) {
    const latestPs = currency.ps?.[currency.ps.length - 1] || {};
    const buy = latestPs.bp || 0;
    const sell = latestPs.sp || 0;
    const price = sell || buy;
    const name = translations[currentLang].currencies[currency.ab.toLowerCase()] || currency.en;

    const allPrices = historyPoints.map(p => p.sp || p.bp || 0).filter(Boolean);
    const high = allPrices.length ? Math.max(...allPrices) : 0;
    const low  = allPrices.length ? Math.min(...allPrices) : 0;
    const oldest = allPrices[0] || price;
    const pctChange = oldest ? (((price - oldest) / oldest) * 100).toFixed(2) : '0.00';
    const isUp = parseFloat(pctChange) >= 0;
    const chartPts = [...allPrices].reverse();

    return `
        <div class="cmodal-header">
            <div class="cmodal-flag" aria-hidden="true">${currency.av || ''}</div>
            <div class="cmodal-title-block">
                <div class="cmodal-code" id="cmodalTitle">${currency.ab.toUpperCase()}</div>
                <div class="cmodal-name">${name}</div>
            </div>
            <div class="cmodal-price-block">
                <div class="cmodal-price">${formatPrice(price)}</div>
                <div class="cmodal-change ${isUp ? 'positive' : 'negative'}">${isUp ? '+' : ''}${pctChange}%</div>
            </div>
        </div>
        <div class="cmodal-chart-wrap">
            <div class="cmodal-chart-label">${t.chartLabel}</div>
            <div class="cmodal-chart">${_drawSparkChart(chartPts, isUp)}</div>
        </div>
        <div class="cmodal-stats">
            <div class="cmodal-stat">
                <span class="cmodal-stat-label">${t.buy}</span>
                <span class="cmodal-stat-value">${formatPrice(buy)}</span>
            </div>
            <div class="cmodal-stat">
                <span class="cmodal-stat-label">${t.sell}</span>
                <span class="cmodal-stat-value">${formatPrice(sell)}</span>
            </div>
            <div class="cmodal-stat">
                <span class="cmodal-stat-label">${t.high}</span>
                <span class="cmodal-stat-value">${formatPrice(high)}</span>
            </div>
            <div class="cmodal-stat">
                <span class="cmodal-stat-label">${t.low}</span>
                <span class="cmodal-stat-value">${formatPrice(low)}</span>
            </div>
        </div>
        <div class="cmodal-ai">
            <div class="cmodal-ai-header">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                    <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/>
                </svg>
                ${t.aiTitle}
            </div>
            <div class="cmodal-ai-body" id="cmodalAiBody">
                <div class="cmodal-ai-loading">${t.aiLoading}</div>
            </div>
        </div>`;
}

function _renderAiResult(pred, currentPrice, t) {
    const predictedPrice = pred.price || 0;
    const pct = currentPrice > 0 ? (((predictedPrice - currentPrice) / currentPrice) * 100).toFixed(1) : '0.0';
    const isUp = parseFloat(pct) > 0;
    const isDown = parseFloat(pct) < 0;
    const confidence = pred.confidence ? Math.round(pred.confidence * 100) : 0;
    const trend = pred.trend || 'neutral';
    const tLabel = translations[currentLang].predictions;
    const trendLabel = trend === 'up' ? tLabel.up : trend === 'down' ? tLabel.down : tLabel.neutral;

    return `
        <div class="cmodal-ai-row">
            <span class="cmodal-ai-row-label">${t.predicted}</span>
            <span class="cmodal-ai-row-value ${isUp ? 'positive' : isDown ? 'negative' : ''}">${formatPrice(predictedPrice)}</span>
        </div>
        <div class="cmodal-ai-row">
            <span class="cmodal-ai-row-label">${t.trend}</span>
            <span class="cmodal-ai-trend ${trend}">${trendLabel}</span>
        </div>
        <div class="cmodal-ai-row">
            <span class="cmodal-ai-row-label">${t.confidence}</span>
            <span class="cmodal-ai-row-value">${confidence}%</span>
        </div>
        <div class="cmodal-ai-confidence">
            <div class="cmodal-ai-confidence-bar" style="width:${confidence}%"></div>
        </div>`;
}

async function openCurrencyModal(currencyData) {
    const modal = document.getElementById('currencyModal');
    const content = document.getElementById('currencyModalContent');
    if (!modal || !content) return;

    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';

    const t = translations[currentLang].currencyModal;

    if (!auth.isPremium()) {
        content.innerHTML = _renderCurrencyGate(currencyData);
        document.getElementById('cmodalUpgradeBtn')?.addEventListener('click', () => {
            closeCurrencyModal();
            if (auth.isLoggedIn()) openAuthModal('upgrade');
            else openAuthModal('register');
        });
        return;
    }

    // Premium: show skeleton, then load data
    content.innerHTML = '<div style="height:320px;display:flex;align-items:center;justify-content:center;color:var(--text-secondary)">Loading…</div>';

    const code = currencyData.ab.toLowerCase();

    // Fetch history (cached per session)
    let historyPoints = [];
    try {
        if (!_historyCache['1w']) {
            const res = await fetch(`${_isGitHubPages ? 'https://linx64.github.io/CurrencyCapPortal/api' : '/api'}/history/1w`);
            _historyCache['1w'] = await res.json();
        }
        const historyData = _historyCache['1w'];
        const entry = historyData.find(c => c.ab?.toLowerCase() === code);
        historyPoints = entry?.ps || [];
    } catch (_) { /* show chart empty */ }

    content.innerHTML = _renderCurrencyContent(currencyData, historyPoints, t);

    // Fetch AI prediction async — update AI block when ready
    const aiBody = document.getElementById('cmodalAiBody');
    try {
        const res = await authFetch('/api/v1/predict', {
            method: 'POST',
            body: JSON.stringify({ currencyCode: code, daysAhead: 7, useML: true })
        });
        const data = await res.json();
        if (res.ok && data.predictions?.[0] && aiBody) {
            const currentPrice = data.currentPrice?.sell || data.currentPrice?.buy || 0;
            aiBody.innerHTML = _renderAiResult(data.predictions[0], currentPrice, t);
        } else if (aiBody) {
            aiBody.innerHTML = `<div class="cmodal-ai-error">${t.aiError}</div>`;
        }
    } catch (_) {
        if (aiBody) aiBody.innerHTML = `<div class="cmodal-ai-error">${t.aiError}</div>`;
    }
}

function closeCurrencyModal() {
    const modal = document.getElementById('currencyModal');
    if (modal) modal.style.display = 'none';
    document.body.style.overflow = '';
}

// Wire up modal close
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('currencyModalClose')?.addEventListener('click', closeCurrencyModal);
    document.getElementById('currencyModal')?.addEventListener('click', e => {
        if (e.target.id === 'currencyModal') closeCurrencyModal();
    });
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') closeCurrencyModal();
    });
});

// Wire up price card clicks via event delegation (re-runs after each price update)
function initCardClicks() {
    const grid = document.querySelector('.prices-grid');
    if (!grid || grid._cardClickBound) return;
    grid._cardClickBound = true;
    grid.addEventListener('click', e => {
        const card = e.target.closest('.price-item');
        if (!card) return;
        const code = card.dataset.currency?.toLowerCase();
        // Find currency data from the last fetched prices
        const currency = _lastPrices?.find(c => c.ab?.toLowerCase() === code);
        if (currency) openCurrencyModal(currency);
    });
}

// Store last fetched prices so card clicks can reference them
let _lastPrices = null;

console.log('%c🚀 Gheymat - AI Currency Predictions', 'color: #5C3DF5; font-size: 16px; font-weight: bold;');
console.log('%cBuilt with modern web technologies', 'color: #7B62F5; font-size: 12px;');
