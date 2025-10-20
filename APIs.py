from enum import Enum


class APIs(Enum):
    HANSHA_LATEST = {
        'title': 'Hansha Latest Rates',
        'url': 'https://hansha.online/latest'
    }
    HANSHA_HISTORY = {
        'title': 'Hansha History',
        'url': 'https://hansha.online/history'
    }
    CRYPTO_RATES = {
        'title': 'CoinGecko Crypto Rates',
        'url': 'https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=100'
               '&page=1&sparkline=false'
    }
    BONBAST = {
        'title': 'Bonbast Currency',
        'url': 'bonbast export'
    }

    @property
    def title(self):
        return self.value['title']

    @property
    def url(self):
        return self.value['url']
