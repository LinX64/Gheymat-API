"""
auth.py — JWT + SQLite authentication module for CurrencyCapPortal

User tiers:
  - free: access to prices, history, pre-generated predictions
  - premium: access to live /api/v1/predict endpoint
"""

import sqlite3
import hashlib
import hmac
import os
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import request, jsonify

try:
    import jwt as pyjwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False
    print("Warning: PyJWT not installed. Auth endpoints will be disabled.")

DB_PATH = os.environ.get('USERS_DB_PATH', 'data/users.db')
JWT_SECRET = os.environ.get('JWT_SECRET', 'gheymat-dev-secret-change-in-production')
JWT_ALGORITHM = 'HS256'
ACCESS_TOKEN_HOURS = 24
REFRESH_TOKEN_DAYS = 30


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def _get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist. Called once at startup."""
    conn = _get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id          TEXT PRIMARY KEY,
            email       TEXT UNIQUE NOT NULL,
            name        TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            tier        TEXT NOT NULL DEFAULT 'free',
            created_at  TEXT NOT NULL,
            last_login  TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS price_alerts (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            currency    TEXT NOT NULL,
            target_price REAL NOT NULL,
            direction   TEXT NOT NULL,
            active      INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT NOT NULL,
            triggered_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    conn.commit()
    conn.close()
    _seed_startup_users()


def _seed_startup_users():
    """
    Seed test users from environment variables on every startup.
    Users are upserted so they survive container restarts.

    Env vars (all optional):
      SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD / SEED_ADMIN_NAME
      SEED_PREMIUM_EMAIL / SEED_PREMIUM_PASSWORD / SEED_PREMIUM_NAME
    """
    seeds = []

    admin_email = os.environ.get('SEED_ADMIN_EMAIL')
    admin_pass  = os.environ.get('SEED_ADMIN_PASSWORD')
    admin_name  = os.environ.get('SEED_ADMIN_NAME', 'Admin')
    if admin_email and admin_pass:
        seeds.append((admin_email, admin_pass, admin_name, 'admin'))

    prem_email = os.environ.get('SEED_PREMIUM_EMAIL')
    prem_pass  = os.environ.get('SEED_PREMIUM_PASSWORD')
    prem_name  = os.environ.get('SEED_PREMIUM_NAME', 'Premium Tester')
    if prem_email and prem_pass:
        seeds.append((prem_email, prem_pass, prem_name, 'premium'))

    if not seeds:
        return

    conn = _get_db()
    now = datetime.now(timezone.utc).isoformat()
    for email, password, name, tier in seeds:
        existing = conn.execute('SELECT id, password_hash FROM users WHERE email = ?', (email,)).fetchone()
        if existing:
            # Update tier and refresh password hash so env-var changes take effect
            conn.execute(
                'UPDATE users SET tier = ?, password_hash = ? WHERE email = ?',
                (tier, _make_password(password), email)
            )
            print(f"✓ Seeded user refreshed: {email} ({tier})")
        else:
            user_id = str(uuid.uuid4())
            conn.execute(
                'INSERT INTO users (id, email, name, password_hash, tier, created_at) VALUES (?,?,?,?,?,?)',
                (user_id, email, name, _make_password(password), tier, now)
            )
            print(f"✓ Seeded user created: {email} ({tier})")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def _hash_password(password: str, salt: str) -> str:
    return hmac.new(
        salt.encode(),
        password.encode(),
        hashlib.sha256
    ).hexdigest()


def _make_password(password: str) -> str:
    """Return 'salt$hash' string suitable for storing in DB."""
    salt = os.urandom(16).hex()
    h = _hash_password(password, salt)
    return f"{salt}${h}"


def _check_password(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split('$', 1)
        return hmac.compare_digest(_hash_password(password, salt), h)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _create_token(user_id: str, token_type: str = 'access') -> str:
    if not JWT_AVAILABLE:
        return ''
    if token_type == 'access':
        exp = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_HOURS)
    else:
        exp = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_DAYS)

    payload = {
        'sub': user_id,
        'type': token_type,
        'iat': datetime.now(timezone.utc),
        'exp': exp,
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _verify_token(token: str) -> dict | None:
    if not JWT_AVAILABLE:
        return None
    try:
        return pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except pyjwt.ExpiredSignatureError:
        return None
    except pyjwt.InvalidTokenError:
        return None


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def _bearer_token() -> str | None:
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        return auth[7:]
    return None


def get_current_user() -> dict | None:
    """Return user dict if the request carries a valid access token, else None."""
    token = _bearer_token()
    if not token:
        return None
    payload = _verify_token(token)
    if not payload or payload.get('type') != 'access':
        return None
    conn = _get_db()
    row = conn.execute('SELECT * FROM users WHERE id = ?', (payload['sub'],)).fetchone()
    conn.close()
    return dict(row) if row else None


def require_auth(f):
    """Decorator: 401 if request has no valid token."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required'}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return wrapped


def require_premium(f):
    """Decorator: 401 if no token, 403 if not premium."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required', 'code': 'AUTH_REQUIRED'}), 401
        if user.get('tier') not in ('premium', 'admin'):
            return jsonify({
                'error': 'Premium subscription required',
                'code': 'PREMIUM_REQUIRED',
                'message': 'Upgrade to Premium to access live AI predictions.'
            }), 403
        request.current_user = user
        return f(*args, **kwargs)
    return wrapped


def require_admin(f):
    """Decorator: 401 if no token, 403 if not admin."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required', 'code': 'AUTH_REQUIRED'}), 401
        if user.get('tier') != 'admin':
            return jsonify({'error': 'Admin access required', 'code': 'ADMIN_REQUIRED'}), 403
        request.current_user = user
        return f(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# Admin route handlers
# ---------------------------------------------------------------------------

def handle_admin_stats():
    """GET /api/admin/stats — system stats"""
    conn = _get_db()
    total = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    premium = conn.execute("SELECT COUNT(*) FROM users WHERE tier = 'premium'").fetchone()[0]
    admins = conn.execute("SELECT COUNT(*) FROM users WHERE tier = 'admin'").fetchone()[0]
    free = conn.execute("SELECT COUNT(*) FROM users WHERE tier = 'free'").fetchone()[0]
    recent = conn.execute(
        "SELECT COUNT(*) FROM users WHERE created_at >= datetime('now', '-7 days')"
    ).fetchone()[0]
    conn.close()
    return jsonify({
        'total': total, 'premium': premium, 'free': free,
        'admin': admins, 'newLast7Days': recent
    }), 200


def handle_admin_list_users():
    """GET /api/admin/users — list all users"""
    conn = _get_db()
    rows = conn.execute(
        'SELECT id, email, name, tier, created_at, last_login FROM users ORDER BY created_at DESC'
    ).fetchall()
    conn.close()
    return jsonify({'users': [dict(r) for r in rows]}), 200


def handle_admin_update_user(user_id: str):
    """PATCH /api/admin/users/<id> — update tier"""
    data = request.get_json() or {}
    new_tier = data.get('tier')
    if new_tier not in ('free', 'premium', 'admin'):
        return jsonify({'error': 'tier must be free, premium, or admin'}), 400
    conn = _get_db()
    result = conn.execute('UPDATE users SET tier = ? WHERE id = ?', (new_tier, user_id))
    conn.commit()
    conn.close()
    if result.rowcount == 0:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({'ok': True, 'tier': new_tier}), 200


def handle_admin_delete_user(user_id: str):
    """DELETE /api/admin/users/<id>"""
    current = get_current_user()
    if current and current['id'] == user_id:
        return jsonify({'error': 'Cannot delete your own account'}), 400
    conn = _get_db()
    result = conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    if result.rowcount == 0:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({'ok': True}), 200


# ---------------------------------------------------------------------------
# Auth route handlers (called from api_server.py)
# ---------------------------------------------------------------------------

def _user_public(row: dict) -> dict:
    return {
        'id': row['id'],
        'email': row['email'],
        'name': row['name'],
        'tier': row['tier'],
        'createdAt': row['created_at'],
    }


def handle_register():
    """POST /api/auth/register"""
    if not JWT_AVAILABLE:
        return jsonify({'error': 'Auth module not available'}), 503

    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    name = (data.get('name') or '').strip()

    if not email or '@' not in email:
        return jsonify({'error': 'Valid email required'}), 400
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400
    if not name:
        return jsonify({'error': 'Name required'}), 400

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    try:
        conn = _get_db()
        conn.execute(
            'INSERT INTO users (id, email, name, password_hash, tier, created_at) VALUES (?,?,?,?,?,?)',
            (user_id, email, name, _make_password(password), 'free', now)
        )
        conn.commit()
        conn.close()
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Email already registered'}), 409

    access_token = _create_token(user_id, 'access')
    refresh_token = _create_token(user_id, 'refresh')

    return jsonify({
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_type': 'Bearer',
        'user': {'id': user_id, 'email': email, 'name': name, 'tier': 'free', 'createdAt': now}
    }), 201


def handle_login():
    """POST /api/auth/login"""
    if not JWT_AVAILABLE:
        return jsonify({'error': 'Auth module not available'}), 503

    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    conn = _get_db()
    row = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    if not row or not _check_password(password, row['password_hash']):
        conn.close()
        return jsonify({'error': 'Invalid email or password'}), 401

    # Update last_login
    now = datetime.now(timezone.utc).isoformat()
    conn.execute('UPDATE users SET last_login = ? WHERE id = ?', (now, row['id']))
    conn.commit()
    conn.close()

    user = dict(row)
    access_token = _create_token(user['id'], 'access')
    refresh_token = _create_token(user['id'], 'refresh')

    return jsonify({
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_type': 'Bearer',
        'user': _user_public(user)
    }), 200


def handle_me():
    """GET /api/auth/me — requires auth"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401
    return jsonify({'user': _user_public(user)}), 200


def handle_refresh():
    """POST /api/auth/refresh — swap refresh token for new access token"""
    if not JWT_AVAILABLE:
        return jsonify({'error': 'Auth module not available'}), 503

    data = request.get_json() or {}
    refresh_token = data.get('refresh_token') or _bearer_token()
    if not refresh_token:
        return jsonify({'error': 'refresh_token required'}), 400

    payload = _verify_token(refresh_token)
    if not payload or payload.get('type') != 'refresh':
        return jsonify({'error': 'Invalid or expired refresh token'}), 401

    conn = _get_db()
    row = conn.execute('SELECT * FROM users WHERE id = ?', (payload['sub'],)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'User not found'}), 404

    new_access = _create_token(row['id'], 'access')
    return jsonify({
        'access_token': new_access,
        'token_type': 'Bearer',
        'user': _user_public(dict(row))
    }), 200


# ---------------------------------------------------------------------------
# Upgrade handler (demo — no payment; in prod gate behind payment webhook)
# ---------------------------------------------------------------------------

def handle_upgrade():
    """POST /api/auth/upgrade — upgrade current user to premium (demo mode)."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required', 'code': 'AUTH_REQUIRED'}), 401
    if user.get('tier') in ('premium', 'admin'):
        return jsonify({'ok': True, 'message': 'Already premium', 'user': _user_public(user)}), 200
    conn = _get_db()
    conn.execute('UPDATE users SET tier = ? WHERE id = ?', ('premium', user['id']))
    conn.commit()
    row = conn.execute('SELECT * FROM users WHERE id = ?', (user['id'],)).fetchone()
    conn.close()
    return jsonify({'ok': True, 'message': 'Upgraded to premium', 'user': _user_public(dict(row))}), 200


# ---------------------------------------------------------------------------
# Price alerts handlers
# ---------------------------------------------------------------------------

FREE_ALERT_LIMIT = 2


def handle_create_alert():
    """POST /api/alerts — create a price alert."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required', 'code': 'AUTH_REQUIRED'}), 401

    data = request.get_json() or {}
    currency = (data.get('currency') or '').strip().lower()
    target_price = data.get('targetPrice')
    direction = (data.get('direction') or '').upper()

    if not currency:
        return jsonify({'error': 'currency is required'}), 400
    if target_price is None or not isinstance(target_price, (int, float)) or target_price <= 0:
        return jsonify({'error': 'targetPrice must be a positive number'}), 400
    if direction not in ('ABOVE', 'BELOW'):
        return jsonify({'error': "direction must be 'ABOVE' or 'BELOW'"}), 400

    conn = _get_db()
    # Free tier: max 2 active alerts
    if user.get('tier') == 'free':
        count = conn.execute(
            "SELECT COUNT(*) FROM price_alerts WHERE user_id = ? AND active = 1", (user['id'],)
        ).fetchone()[0]
        if count >= FREE_ALERT_LIMIT:
            conn.close()
            return jsonify({
                'error': f'Free tier is limited to {FREE_ALERT_LIMIT} active alerts. Upgrade to Premium for unlimited alerts.',
                'code': 'ALERT_LIMIT_REACHED'
            }), 403

    alert_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        'INSERT INTO price_alerts (id, user_id, currency, target_price, direction, active, created_at) VALUES (?,?,?,?,?,1,?)',
        (alert_id, user['id'], currency, float(target_price), direction, now)
    )
    conn.commit()
    conn.close()
    return jsonify({
        'ok': True,
        'alert': {'id': alert_id, 'currency': currency, 'targetPrice': target_price,
                  'direction': direction, 'active': True, 'createdAt': now}
    }), 201


def handle_list_alerts():
    """GET /api/alerts — list current user's alerts."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required', 'code': 'AUTH_REQUIRED'}), 401
    conn = _get_db()
    rows = conn.execute(
        'SELECT * FROM price_alerts WHERE user_id = ? ORDER BY created_at DESC', (user['id'],)
    ).fetchall()
    conn.close()
    alerts = [{
        'id': r['id'], 'currency': r['currency'], 'targetPrice': r['target_price'],
        'direction': r['direction'], 'active': bool(r['active']),
        'createdAt': r['created_at'], 'triggeredAt': r['triggered_at']
    } for r in rows]
    tier = user.get('tier', 'free')
    limit = None if tier in ('premium', 'admin') else FREE_ALERT_LIMIT
    return jsonify({'alerts': alerts, 'tier': tier, 'limit': limit}), 200


def handle_delete_alert(alert_id: str):
    """DELETE /api/alerts/<id> — delete an alert belonging to current user."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required', 'code': 'AUTH_REQUIRED'}), 401
    conn = _get_db()
    result = conn.execute(
        'DELETE FROM price_alerts WHERE id = ? AND user_id = ?', (alert_id, user['id'])
    )
    conn.commit()
    conn.close()
    if result.rowcount == 0:
        return jsonify({'error': 'Alert not found'}), 404
    return jsonify({'ok': True}), 200


def check_and_trigger_alerts(latest_prices: dict):
    """
    Called periodically with current prices dict {currency_code: buy_price}.
    Marks matching alerts as triggered.
    Returns list of triggered alert dicts for optional notification.
    """
    if not latest_prices:
        return []
    conn = _get_db()
    active = conn.execute(
        "SELECT * FROM price_alerts WHERE active = 1"
    ).fetchall()
    triggered = []
    now = datetime.now(timezone.utc).isoformat()
    for alert in active:
        currency = alert['currency']
        price = latest_prices.get(currency)
        if price is None:
            continue
        hit = (alert['direction'] == 'ABOVE' and price >= alert['target_price']) or \
              (alert['direction'] == 'BELOW' and price <= alert['target_price'])
        if hit:
            conn.execute(
                'UPDATE price_alerts SET active = 0, triggered_at = ? WHERE id = ?',
                (now, alert['id'])
            )
            triggered.append(dict(alert))
    if triggered:
        conn.commit()
    conn.close()
    return triggered
