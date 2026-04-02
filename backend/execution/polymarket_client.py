"""
Polymarket CLOB Client for Order Execution

Interfaces with Polymarket's CLOB API for:
1. Order placement (limit orders)
2. Order cancellation
3. Order status queries
4. Position queries
5. Balance queries

Authentication uses Polymarket API keys + HMAC signing.

Reference: Polymarket CLOB API docs
- Base URL: https://clob.polymarket.com
- Order placement: POST /order
- Cancel: DELETE /order/{orderId}
- Open orders: GET /orders
"""

import time
import hmac
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from enum import Enum

logger = logging.getLogger(__name__)


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    GTC = "GTC"   # Good til cancelled
    GTD = "GTD"   # Good til date
    FOK = "FOK"   # Fill or kill


@dataclass
class OrderRequest:
    """Order to be placed on Polymarket CLOB."""
    token_id: str
    side: OrderSide
    price: float         # Price in [0.01, 0.99]
    size: float          # Size in USDC
    order_type: OrderType = OrderType.GTC
    expiration: Optional[int] = None  # Unix timestamp for GTD

    def to_api_payload(self) -> dict:
        """Convert to Polymarket API format."""
        payload = {
            "tokenID": self.token_id,
            "side": self.side.value,
            "price": str(round(self.price, 2)),
            "size": str(round(self.size, 2)),
            "type": self.order_type.value,
        }
        if self.expiration and self.order_type == OrderType.GTD:
            payload["expiration"] = str(self.expiration)
        return payload


@dataclass
class OrderResponse:
    """Response from Polymarket after order placement."""
    order_id: str = ""
    status: str = ""         # LIVE, MATCHED, CANCELLED
    size_matched: float = 0.0
    price: float = 0.0
    side: str = ""
    token_id: str = ""
    timestamp: float = 0.0
    error: Optional[str] = None


@dataclass
class PositionInfo:
    """Current position in a market."""
    token_id: str
    size: float           # Number of contracts
    avg_price: float      # Average entry price
    side: str             # Which token held


class PolymarketExecutionClient:
    """
    Client for executing trades on Polymarket CLOB.

    In production, this connects to the real API.
    For development/testing, operates in paper trading mode.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None,
        base_url: str = "https://clob.polymarket.com",
        paper_mode: bool = True,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        self.base_url = base_url
        self.paper_mode = paper_mode

        # Paper trading state
        self._paper_orders: Dict[str, OrderResponse] = {}
        self._paper_positions: Dict[str, PositionInfo] = {}
        self._paper_balance: float = 10000.0
        self._paper_order_counter: int = 0

        if paper_mode:
            logger.info("PolymarketExecutionClient initialized in PAPER TRADING mode")
        else:
            if not all([api_key, api_secret, api_passphrase]):
                raise ValueError(
                    "api_key, api_secret, and api_passphrase required for live trading"
                )
            logger.info("PolymarketExecutionClient initialized in LIVE mode")

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        """
        Place an order on Polymarket CLOB.

        In paper mode, simulates immediate fill at requested price.
        In live mode, sends order to API.
        """
        if self.paper_mode:
            return self._paper_fill(order)

        return await self._live_place_order(order)

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        if self.paper_mode:
            if order_id in self._paper_orders:
                self._paper_orders[order_id].status = "CANCELLED"
                return True
            return False

        return await self._live_cancel_order(order_id)

    async def get_open_orders(self, token_id: Optional[str] = None) -> List[OrderResponse]:
        """Get open orders, optionally filtered by token."""
        if self.paper_mode:
            orders = list(self._paper_orders.values())
            if token_id:
                orders = [o for o in orders if o.token_id == token_id]
            return [o for o in orders if o.status == "LIVE"]

        return await self._live_get_orders(token_id)

    async def get_positions(self) -> Dict[str, PositionInfo]:
        """Get all current positions."""
        if self.paper_mode:
            return dict(self._paper_positions)

        return await self._live_get_positions()

    async def get_balance(self) -> float:
        """Get available USDC balance."""
        if self.paper_mode:
            return self._paper_balance

        return await self._live_get_balance()

    # --- Paper trading implementation ---

    def _paper_fill(self, order: OrderRequest) -> OrderResponse:
        """Simulate order fill in paper mode."""
        self._paper_order_counter += 1
        order_id = f"paper_{self._paper_order_counter}"

        cost = order.size  # USDC cost
        if cost > self._paper_balance:
            return OrderResponse(
                order_id=order_id,
                status="REJECTED",
                error="Insufficient balance",
                token_id=order.token_id,
            )

        # Simulate fill
        self._paper_balance -= cost
        qty = order.size / order.price  # Number of contracts

        response = OrderResponse(
            order_id=order_id,
            status="MATCHED",
            size_matched=order.size,
            price=order.price,
            side=order.side.value,
            token_id=order.token_id,
            timestamp=time.time(),
        )

        # Update position
        existing = self._paper_positions.get(order.token_id)
        if existing:
            total_qty = existing.size + qty
            if total_qty > 0:
                existing.avg_price = (
                    existing.avg_price * existing.size + order.price * qty
                ) / total_qty
                existing.size = total_qty
        else:
            self._paper_positions[order.token_id] = PositionInfo(
                token_id=order.token_id,
                size=qty,
                avg_price=order.price,
                side=order.side.value,
            )

        self._paper_orders[order_id] = response
        logger.info(
            f"[PAPER] Order filled: {order.side.value} {order.size:.2f} USDC "
            f"@ {order.price:.4f} for {order.token_id[:8]}..."
        )
        return response

    def paper_settle(self, token_id: str, outcome_price: float) -> float:
        """
        Settle a paper position (market resolved).

        Args:
            token_id: Token that resolved
            outcome_price: 1.0 if YES won, 0.0 if NO won

        Returns:
            PnL from settlement
        """
        pos = self._paper_positions.pop(token_id, None)
        if pos is None:
            return 0.0

        payout = pos.size * outcome_price
        self._paper_balance += payout
        pnl = payout - pos.size * pos.avg_price

        logger.info(
            f"[PAPER] Settlement: {token_id[:8]}... "
            f"payout=${payout:.2f} pnl=${pnl:.2f}"
        )
        return pnl

    # --- Live trading implementation (stubs) ---

    async def _live_place_order(self, order: OrderRequest) -> OrderResponse:
        """Place order via Polymarket API."""
        import aiohttp

        headers = self._build_headers("POST", "/order", order.to_api_payload())
        url = f"{self.base_url}/order"

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=order.to_api_payload(), headers=headers
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return OrderResponse(
                        order_id=data.get("orderID", ""),
                        status=data.get("status", ""),
                        size_matched=float(data.get("sizeMatched", 0)),
                        price=float(data.get("price", 0)),
                        side=data.get("side", ""),
                        token_id=order.token_id,
                        timestamp=time.time(),
                    )
                else:
                    error_text = await resp.text()
                    logger.error(f"Order placement failed: {resp.status} {error_text}")
                    return OrderResponse(
                        status="REJECTED",
                        error=error_text,
                        token_id=order.token_id,
                    )

    async def _live_cancel_order(self, order_id: str) -> bool:
        import aiohttp

        headers = self._build_headers("DELETE", f"/order/{order_id}")
        url = f"{self.base_url}/order/{order_id}"

        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers) as resp:
                return resp.status == 200

    async def _live_get_orders(self, token_id: Optional[str]) -> List[OrderResponse]:
        import aiohttp

        params = {}
        if token_id:
            params["asset_id"] = token_id

        headers = self._build_headers("GET", "/orders")
        url = f"{self.base_url}/orders"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [
                        OrderResponse(
                            order_id=o.get("id", ""),
                            status=o.get("status", ""),
                            size_matched=float(o.get("size_matched", 0)),
                            price=float(o.get("price", 0)),
                            side=o.get("side", ""),
                            token_id=o.get("asset_id", ""),
                        )
                        for o in data
                    ]
                return []

    async def _live_get_positions(self) -> Dict[str, PositionInfo]:
        # Implementation depends on Polymarket's position API
        return {}

    async def _live_get_balance(self) -> float:
        # Implementation depends on Polymarket's balance API
        return 0.0

    def _build_headers(self, method: str, path: str, body: dict = None) -> dict:
        """Build authenticated headers for Polymarket API."""
        timestamp = str(int(time.time()))
        body_str = json.dumps(body) if body else ""
        message = f"{timestamp}{method}{path}{body_str}"

        signature = hmac.new(
            self.api_secret.encode() if self.api_secret else b"",
            message.encode(),
            hashlib.sha256,
        ).hexdigest()

        return {
            "Content-Type": "application/json",
            "POLY-API-KEY": self.api_key or "",
            "POLY-SIGNATURE": signature,
            "POLY-TIMESTAMP": timestamp,
            "POLY-PASSPHRASE": self.api_passphrase or "",
        }
