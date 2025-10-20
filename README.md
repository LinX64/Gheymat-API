# Currency Cap Portal

CurrencyCap project backend

## Quick start

1. Download the project folder to your computer

2. Make a virtual python environment

  ```
  python3 -m venv .venv
  ```

Enable the environment and install the required packages

  ```
  source .venv/bin/activate
  pip install -r requirements.txt
  ```

To run the app open the project in PyCharm and set the .venv file as the interpreter and the run.py file as the
   starter file

## Mobile-Friendly History API

Clean, simple period-based endpoints with automatic **Hansha → Bonbast fallback**!

### Quick Start (No Date Calculation Needed!)

```javascript
// Get yesterday's rates
const yesterday = await fetch('https://linx64.github.io/CurrencyCapPortal/history/1d.json')
  .then(res => res.json());

// Get last week for charts
const weekData = await fetch('https://linx64.github.io/CurrencyCapPortal/history/1w.json')
  .then(res => res.json());

// Get last month for trends
const monthData = await fetch('https://linx64.github.io/CurrencyCapPortal/history/1m.json')
  .then(res => res.json());

// Get last year for analysis
const yearData = await fetch('https://linx64.github.io/CurrencyCapPortal/history/1y.json')
  .then(res => res.json());
```

### Available Endpoints

| Endpoint | Period | Data Source |
|----------|--------|-------------|
| `/history/1d.json` | Yesterday | Hansha → Bonbast (1 day) |
| `/history/1w.json` | Last week | Hansha → Bonbast (7 days) |
| `/history/1m.json` | Last month | Hansha → Bonbast (30 days) |
| `/history/1y.json` | Last year | Hansha → Bonbast (90 days max) |

### Data Formats

**Hansha Format** (primary source):
```json
{
  "ab": "usd",
  "av": "🇺🇸",
  "en": "US Dollar",
  "fa": "دلار آمریکا",
  "ps": [
    { "bp": 108400, "sp": 108520, "ts": "2025-10-19T00:00:00Z" },
    { "bp": 107300, "sp": 107390, "ts": "2025-10-18T00:00:00Z" }
  ]
}
```

**Bonbast Format** (fallback):
```json
[
  {
    "date": "2025-10-19",
    "rates": {
      "usd": { "name": "US Dollar", "sell": 108500, "buy": 108400 },
      "eur": { "name": "Euro", "sell": 126500, "buy": 126300 }
    }
  }
]
```

### Generating Custom Date History

For specific dates not pre-generated, use the `generate_history_date.py` script:

```bash
# Generate history for October 10, 2020
python3 generate_history_date.py 2020-10-10

# Also supports slash format
python3 generate_history_date.py 2020/10/10
```

**Valid Date Range:** 2012-10-09 to one day before current date (Gregorian calendar)

This creates: `api/history/2020-10-10.json` accessible at:
```
https://linx64.github.io/CurrencyCapPortal/history/2020-10-10.json
```

## Used APIs in this project

### Bonbast
Library's Github repo: https://github.com/SamadiPour/bonbast
