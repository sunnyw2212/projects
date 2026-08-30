"""
kalshi_client.py — Minimal Kalshi API client (REST v2)

Public market data (prices, order books, events, series, trade history)
needs no credentials at all. Authenticated endpoints (balance, positions,
orders, fills) require an API key ID + RSA-PSS signed requests.

Get an API key pair from your Kalshi account settings (kalshi.com ->
Account -> API Keys). Kalshi gives you the private key once as a .pem
file — save it somewhere safe.

Usage:
    from kalshi_client import KalshiClient

    # Public data only — no credentials needed
    client = KalshiClient()
    markets = client.get_markets(status="open", limit=20)
    for m in markets["markets"]:
        print(m["ticker"], m["yes_bid"], m["yes_ask"], m["volume"])

    # Authenticated (portfolio, orders, balance)
    client = KalshiClient(
        api_key_id="your-key-id",
        private_key_path="path/to/private_key.pem",
    )
    print(client.get_balance())

    # Use the free-money demo environment instead of live trading
    client = KalshiClient(demo=True)
"""

import time
import base64
import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
DEMO_BASE_URL = "https://demo-api.kalshi.co/trade-api/v2"


class KalshiClient:
    def __init__(self, api_key_id: str = None, private_key_path: str = None, demo: bool = False):
        self.base_url = DEMO_BASE_URL if demo else BASE_URL
        self.api_key_id = api_key_id
        self.private_key = None
        if private_key_path:
            with open(private_key_path, "rb") as f:
                self.private_key = serialization.load_pem_private_key(f.read(), password=None)
        self._http = httpx.Client(base_url=self.base_url, timeout=30)

    def _sign_headers(self, method: str, full_path: str) -> dict:
        """Builds the KALSHI-ACCESS-* headers required for authenticated calls."""
        if not self.api_key_id or not self.private_key:
            return {}
        timestamp_ms = str(int(time.time() * 1000))
        message = f"{timestamp_ms}{method}{full_path}".encode("utf-8")
        signature = self.private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        }

    def _get(self, path: str, params: dict = None) -> dict:
        # The signature covers the full API path, including the /trade-api/v2 prefix.
        full_path = f"/trade-api/v2{path}"
        headers = self._sign_headers("GET", full_path)
        resp = self._http.get(path, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()

    # ---------- Public endpoints (no auth required) ----------

    def get_markets(self, **params) -> dict:
        """List markets. Useful params: status='open', series_ticker, limit, cursor."""
        return self._get("/markets", params=params)

    def get_market(self, ticker: str) -> dict:
        return self._get(f"/markets/{ticker}")

    def get_orderbook(self, ticker: str, depth: int = 10) -> dict:
        return self._get(f"/markets/{ticker}/orderbook", params={"depth": depth})

    def get_trades(self, **params) -> dict:
        """Recent public trades. Useful params: ticker, limit, cursor."""
        return self._get("/markets/trades", params=params)

    def get_events(self, **params) -> dict:
        """Useful params: status, series_ticker, limit, cursor."""
        return self._get("/events", params=params)

    def get_series(self, series_ticker: str) -> dict:
        return self._get(f"/series/{series_ticker}")

    def get_candlesticks(self, series_ticker: str, ticker: str, period_interval: int = 60, **params) -> dict:
        """Live-tier candlesticks (recent data only — see get_historical_cutoff)."""
        params["period_interval"] = period_interval
        return self._get(f"/series/{series_ticker}/markets/{ticker}/candlesticks", params=params)

    # ---------- Historical tier (data older than the live cutoff) ----------
    # Kalshi partitions markets, candlesticks, trades, orders, and positions into
    # a fast "live" tier (recent data, ~last 3 months) and a "historical" tier for
    # everything older. Call get_historical_cutoff() to find the current boundary,
    # then route older queries to these endpoints instead of the live ones above.

    def get_historical_cutoff(self) -> dict:
        """Returns the current cutoff timestamp(s) separating live vs. historical data."""
        return self._get("/historical/cutoff")

    def get_historical_markets(self, **params) -> dict:
        return self._get("/historical/markets", params=params)

    def get_historical_candlesticks(self, ticker: str, period_interval: int = 60, **params) -> dict:
        params["period_interval"] = period_interval
        return self._get(f"/historical/markets/{ticker}/candlesticks", params=params)

    def get_historical_trades(self, **params) -> dict:
        return self._get("/historical/markets/trades", params=params)

    # ---------- Authenticated endpoints (need api_key_id + private_key_path) ----------

    def get_balance(self) -> dict:
        return self._get("/portfolio/balance")

    def get_positions(self, **params) -> dict:
        return self._get("/portfolio/positions", params=params)

    def get_orders(self, **params) -> dict:
        return self._get("/portfolio/orders", params=params)

    def get_fills(self, **params) -> dict:
        return self._get("/portfolio/fills", params=params)


if __name__ == "__main__":
    # Quick smoke test using only public data — no credentials needed.
    client = KalshiClient()
    data = client.get_markets(status="open", limit=5)
    for m in data.get("markets", []):
        print(f"{m['ticker']:30s} YES bid/ask: {m['yes_bid_dollars']}/{m['yes_ask_dollars']}  vol: {m['volume_fp']}")
