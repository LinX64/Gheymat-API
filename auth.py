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
