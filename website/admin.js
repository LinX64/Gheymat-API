// ============================================================
// admin.js — Gheymat Admin Dashboard
// ============================================================

const AUTH_API_URL = window.AUTH_API_URL || 'https://gheymat-api-production.up.railway.app';

// ---- Auth state ----
const auth = {
    get token()  { return localStorage.getItem('gheymat_token'); },
    get user()   { try { return JSON.parse(localStorage.getItem('gheymat_user') || 'null'); } catch { return null; } },
    save(data) {
        if (data.access_token)  localStorage.setItem('gheymat_token', data.access_token);
        if (data.refresh_token) localStorage.setItem('gheymat_refresh', data.refresh_token);
        if (data.user)          localStorage.setItem('gheymat_user', JSON.stringify(data.user));
    },
    clear() {
        ['gheymat_token','gheymat_refresh','gheymat_user'].forEach(k => localStorage.removeItem(k));
    },
    isAdmin() { return this.user?.tier === 'admin'; },
    isLoggedIn() { return !!this.token; }
};

async function authFetch(path, opts = {}) {
    const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
    if (auth.token) headers['Authorization'] = `Bearer ${auth.token}`;
    return fetch(`${AUTH_API_URL}${path}`, { ...opts, headers });
}

// ---- Theme ----
function initTheme() {
    const theme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', theme);
    document.getElementById('themeToggle')?.addEventListener('click', () => {
        const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('theme', next);
    });
}

// ---- Gate logic ----
function renderGate() {
    const gate = document.getElementById('adminGate');
    const main = document.getElementById('adminMain');
    const gateMsg = document.getElementById('gateMsg');

    if (!auth.isLoggedIn()) {
        gate.style.display = 'block';
        main.style.display = 'none';
        gateMsg.textContent = 'Sign in to access admin panel.';
    } else if (!auth.isAdmin()) {
        gate.style.display = 'block';
        main.style.display = 'none';
        gateMsg.textContent = 'Admin access required. Your account does not have admin privileges.';
        document.getElementById('gateLoginBtn').textContent = 'Sign Out';
        document.getElementById('gateLoginBtn').onclick = () => { auth.clear(); renderGate(); };
    } else {
        gate.style.display = 'none';
        main.style.display = 'block';
        document.getElementById('adminUserName').textContent = auth.user?.name || '';
        document.getElementById('adminLogoutBtn').style.display = 'inline-flex';
        loadStats();
        loadUsers();
    }
}

// ---- Stats ----
async function loadStats() {
    try {
        const res = await authFetch('/api/admin/stats');
        if (!res.ok) return;
        const d = await res.json();
        document.getElementById('statTotal').textContent   = d.total   ?? '—';
        document.getElementById('statPremium').textContent = d.premium  ?? '—';
        document.getElementById('statFree').textContent    = d.free     ?? '—';
        document.getElementById('statNew').textContent     = d.newLast7Days ?? '—';
    } catch { /* silent */ }
}

// ---- Users ----
let allUsers = [];

async function loadUsers() {
    const tbody = document.getElementById('usersBody');
    tbody.innerHTML = '<tr><td colspan="6" class="rates-loading">Loading users…</td></tr>';
    try {
        const res = await authFetch('/api/admin/users');
        if (!res.ok) throw new Error('Failed');
        const d = await res.json();
        allUsers = d.users || [];
        renderUsers(allUsers);
    } catch {
        tbody.innerHTML = '<tr><td colspan="6" class="rates-loading" style="color:var(--color-negative)">Failed to load users.</td></tr>';
    }
}

function renderUsers(users) {
    const tbody = document.getElementById('usersBody');
    if (!users.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="rates-loading">No users found.</td></tr>';
        return;
    }
    tbody.innerHTML = users.map(u => {
        const joined   = u.created_at ? new Date(u.created_at).toLocaleDateString() : '—';
        const lastLogin = u.last_login ? new Date(u.last_login).toLocaleDateString() : '—';
        const badgeCls = u.tier === 'premium' ? 'premium' : u.tier === 'admin' ? 'admin' : '';
        const initials = (u.name || '?').charAt(0).toUpperCase();
        return `
        <tr>
            <td class="rates-td">
                <div style="display:flex;align-items:center;gap:8px;">
                    <div class="account-avatar" style="width:32px;height:32px;font-size:13px;flex-shrink:0;">${initials}</div>
                    <span>${escHtml(u.name)}</span>
                </div>
            </td>
            <td class="rates-td" style="color:var(--text-secondary);font-size:13px;">${escHtml(u.email)}</td>
            <td class="rates-td">
                <select class="admin-tier-select" data-uid="${escHtml(u.id)}" data-current="${escHtml(u.tier)}">
                    <option value="free"    ${u.tier === 'free'    ? 'selected' : ''}>Free</option>
                    <option value="premium" ${u.tier === 'premium' ? 'selected' : ''}>Premium</option>
                    <option value="admin"   ${u.tier === 'admin'   ? 'selected' : ''}>Admin</option>
                </select>
            </td>
            <td class="rates-td rates-td-time">${joined}</td>
            <td class="rates-td rates-td-time">${lastLogin}</td>
            <td class="rates-td">
                <button class="admin-delete-btn" data-uid="${escHtml(u.id)}" data-name="${escHtml(u.name)}">Delete</button>
            </td>
        </tr>`;
    }).join('');

    // Tier change handler
    tbody.querySelectorAll('.admin-tier-select').forEach(sel => {
        sel.addEventListener('change', async () => {
            const uid = sel.dataset.uid;
            const newTier = sel.value;
            sel.disabled = true;
            try {
                const res = await authFetch(`/api/admin/users/${uid}`, {
                    method: 'PATCH',
                    body: JSON.stringify({ tier: newTier })
                });
                if (!res.ok) throw new Error('Failed');
                sel.dataset.current = newTier;
                // update local cache
                const u = allUsers.find(x => x.id === uid);
                if (u) u.tier = newTier;
                showToast(`Tier updated to ${newTier}`);
            } catch {
                sel.value = sel.dataset.current;
                showToast('Failed to update tier', true);
            } finally {
                sel.disabled = false;
            }
        });
    });

    // Delete handler
    tbody.querySelectorAll('.admin-delete-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const uid  = btn.dataset.uid;
            const name = btn.dataset.name;
            if (!confirm(`Delete user "${name}"? This cannot be undone.`)) return;
            btn.disabled = true;
            try {
                const res = await authFetch(`/api/admin/users/${uid}`, { method: 'DELETE' });
                if (!res.ok) { const d = await res.json(); throw new Error(d.error || 'Failed'); }
                allUsers = allUsers.filter(u => u.id !== uid);
                renderUsers(filterUsers(document.getElementById('userSearch').value));
                loadStats();
                showToast('User deleted');
            } catch (e) {
                showToast(e.message || 'Delete failed', true);
                btn.disabled = false;
            }
        });
    });
}

function filterUsers(q) {
    const s = q.trim().toLowerCase();
    if (!s) return allUsers;
    return allUsers.filter(u =>
        u.name?.toLowerCase().includes(s) || u.email?.toLowerCase().includes(s)
    );
}

// ---- Toast ----
function showToast(msg, isError = false) {
    const el = document.createElement('div');
    el.textContent = msg;
    Object.assign(el.style, {
        position: 'fixed', bottom: '24px', right: '24px', zIndex: '9999',
        padding: '10px 18px', borderRadius: '8px', fontSize: '13px', fontWeight: '600',
        background: isError ? 'var(--color-negative)' : 'var(--text-primary)',
        color: isError ? '#fff' : 'var(--bg-primary)',
        boxShadow: 'var(--shadow-md)', transition: 'opacity 0.3s'
    });
    document.body.appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 2500);
}

// ---- Auth modal ----
function openAuthModal() {
    document.getElementById('authModal').style.display = 'flex';
    document.body.style.overflow = 'hidden';
}
function closeAuthModal() {
    document.getElementById('authModal').style.display = 'none';
    document.body.style.overflow = '';
}

function initAuthModal() {
    document.getElementById('modalClose')?.addEventListener('click', closeAuthModal);
    document.getElementById('authModal')?.addEventListener('click', e => {
        if (e.target.id === 'authModal') closeAuthModal();
    });
    document.getElementById('tabLogin')?.addEventListener('click', () => {
        document.getElementById('loginForm').style.display = 'block';
        document.getElementById('registerForm').style.display = 'none';
        document.getElementById('tabLogin').classList.add('active');
        document.getElementById('tabRegister').classList.remove('active');
    });
    document.getElementById('tabRegister')?.addEventListener('click', () => {
        document.getElementById('loginForm').style.display = 'none';
        document.getElementById('registerForm').style.display = 'block';
        document.getElementById('tabLogin').classList.remove('active');
        document.getElementById('tabRegister').classList.add('active');
    });

    document.getElementById('gateLoginBtn')?.addEventListener('click', () => {
        if (auth.isLoggedIn() && !auth.isAdmin()) return; // already handled above
        openAuthModal();
    });

    document.getElementById('adminLogoutBtn')?.addEventListener('click', () => {
        auth.clear();
        renderGate();
    });

    document.getElementById('loginForm')?.addEventListener('submit', async e => {
        e.preventDefault();
        const email    = document.getElementById('loginEmail').value;
        const password = document.getElementById('loginPassword').value;
        const errEl    = document.getElementById('loginError');
        const btn      = document.getElementById('loginSubmit');
        errEl.textContent = '';
        btn.disabled = true; btn.textContent = '…';
        try {
            const res  = await authFetch('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Login failed');
            auth.save(data);
            closeAuthModal();
            renderGate();
        } catch (err) {
            errEl.textContent = err.message;
        } finally {
            btn.disabled = false; btn.textContent = 'Sign In';
        }
    });

    document.getElementById('registerForm')?.addEventListener('submit', async e => {
        e.preventDefault();
        const name     = document.getElementById('regName').value;
        const email    = document.getElementById('regEmail').value;
        const password = document.getElementById('regPassword').value;
        const errEl    = document.getElementById('registerError');
        const btn      = document.getElementById('registerSubmit');
        errEl.textContent = '';
        btn.disabled = true; btn.textContent = '…';
        try {
            const res  = await authFetch('/api/auth/register', { method: 'POST', body: JSON.stringify({ name, email, password }) });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Registration failed');
            auth.save(data);
            closeAuthModal();
            renderGate();
        } catch (err) {
            errEl.textContent = err.message;
        } finally {
            btn.disabled = false; btn.textContent = 'Create Account';
        }
    });
}

// ---- Utils ----
function escHtml(str) {
    return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ---- Init ----
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initAuthModal();
    renderGate();

    document.getElementById('refreshBtn')?.addEventListener('click', () => {
        loadStats();
        loadUsers();
    });

    document.getElementById('userSearch')?.addEventListener('input', e => {
        renderUsers(filterUsers(e.target.value));
    });
});
