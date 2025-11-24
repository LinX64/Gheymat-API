import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

CACHE_DIR = Path('cache')
CACHE_DIR.mkdir(exist_ok=True)

API_DIR = Path('api')
API_DIR.mkdir(exist_ok=True)

CACHE_EXPIRY = {
    'latest': 5,
    '1d': 60,
    '1w': 360,
    '1m': 720,
    '1y': 1440,
    'crypto': 5,
    'news': 60
}

def load_cache(endpoint: str) -> Optional[Dict[str, Any]]:
    cache_file = CACHE_DIR / f'{endpoint}.json'

    if not cache_file.exists():
        return None

    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)

        cache_time = datetime.fromisoformat(cache_data['cached_at'])
        age_minutes = (datetime.now() - cache_time).total_seconds() / 60
        expiry = CACHE_EXPIRY.get(endpoint, 60)

        if age_minutes < expiry:
            return cache_data['data']
        else:
            return None
    except Exception as e:
        print(f"   ✗ Failed to load cache for {endpoint}: {e}")
        return None


def save_cache(endpoint: str, data: Any) -> None:
    try:
        cache_file = CACHE_DIR / f'{endpoint}.json'
        cache_data = {
            'cached_at': datetime.now().isoformat(),
            'data': data
        }
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"   ⚠ Failed to save cache for {endpoint}: {e}")


def save_api_endpoint(endpoint_path: str, data: Any) -> None:
    output_file = API_DIR / endpoint_path
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"   ✓ Saved {endpoint_path}")
