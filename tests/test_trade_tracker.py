"""Tests for trade_tracker module."""

import time
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from trade_tracker import (
    ActiveTrade,
    TradeStatus,
    register_trade,
    close_trade,
    get_active_trades,
    has_active_trade,
    get_trade,
    update_trades,
    _active_trades,
    _check_sl_tp,
)


@pytest.fixture(autouse=True)
def clear_trades():
    """Ensure a clean slate for each test."""
    _active_trades.clear()
    yield
    _active_trades.clear()


class FakeSignal:
    """Minimal Signal-like object for tests."""
    def __init__(self, symbol="BTC/USDT", direction="BUY",
                 entry_price=50000.0, stop_loss=48000.0,
                 target=54000.0, confidence=0.85):
        self.symbol = symbol
        self.direction = direction
        self.entry_price = entry_price
        self.stop_loss = stop_loss
        self.target = target
        self.confidence = confidence


# ── Registration ─────────────────────────────────────────────────────

def test_register_trade():
    sig = FakeSignal()
    trade = register_trade(sig)

    assert trade.symbol == "BTC/USDT"
    assert trade.direction == "BUY"
    assert trade.entry_price == 50000.0
    assert trade.status == TradeStatus.ACTIVE
    assert has_active_trade("BTC/USDT")


def test_register_replaces_existing():
    register_trade(FakeSignal(direction="BUY"))
    register_trade(FakeSignal(direction="SELL"))

    assert get_trade("BTC/USDT").direction == "SELL"
    assert len(get_active_trades()) == 1


# ── P&L calculations ────────────────────────────────────────────────

def test_pnl_buy_profit():
    trade = ActiveTrade(
        symbol="BTC/USDT", direction="BUY",
        entry_price=50000.0, stop_loss=48000.0, target=54000.0,
        confidence=0.85, current_price=52000.0,
    )
    assert trade.pnl_percent == pytest.approx(4.0, abs=0.01)
    assert trade.pnl_absolute == pytest.approx(2000.0, abs=0.01)


def test_pnl_buy_loss():
    trade = ActiveTrade(
        symbol="BTC/USDT", direction="BUY",
        entry_price=50000.0, stop_loss=48000.0, target=54000.0,
        confidence=0.85, current_price=49000.0,
    )
    assert trade.pnl_percent == pytest.approx(-2.0, abs=0.01)


def test_pnl_sell_profit():
    trade = ActiveTrade(
        symbol="ETH/USDT", direction="SELL",
        entry_price=3000.0, stop_loss=3200.0, target=2600.0,
        confidence=0.8, current_price=2800.0,
    )
    assert trade.pnl_percent == pytest.approx(6.67, abs=0.01)


# ── SL / TP detection ───────────────────────────────────────────────

def test_sl_hit_buy():
    trade = ActiveTrade(
        symbol="BTC/USDT", direction="BUY",
        entry_price=50000.0, stop_loss=48000.0, target=54000.0,
        confidence=0.85, current_price=47500.0,
    )
    assert _check_sl_tp(trade) == TradeStatus.STOP_LOSS_HIT


def test_tp_hit_buy():
    trade = ActiveTrade(
        symbol="BTC/USDT", direction="BUY",
        entry_price=50000.0, stop_loss=48000.0, target=54000.0,
        confidence=0.85, current_price=54500.0,
    )
    assert _check_sl_tp(trade) == TradeStatus.TARGET_HIT


def test_sl_hit_sell():
    trade = ActiveTrade(
        symbol="ETH/USDT", direction="SELL",
        entry_price=3000.0, stop_loss=3200.0, target=2600.0,
        confidence=0.8, current_price=3300.0,
    )
    assert _check_sl_tp(trade) == TradeStatus.STOP_LOSS_HIT


def test_tp_hit_sell():
    trade = ActiveTrade(
        symbol="ETH/USDT", direction="SELL",
        entry_price=3000.0, stop_loss=3200.0, target=2600.0,
        confidence=0.8, current_price=2500.0,
    )
    assert _check_sl_tp(trade) == TradeStatus.TARGET_HIT


def test_active_no_hit():
    trade = ActiveTrade(
        symbol="BTC/USDT", direction="BUY",
        entry_price=50000.0, stop_loss=48000.0, target=54000.0,
        confidence=0.85, current_price=51000.0,
    )
    assert _check_sl_tp(trade) == TradeStatus.ACTIVE


# ── Close trade ──────────────────────────────────────────────────────

def test_close_trade():
    register_trade(FakeSignal())
    closed = close_trade("BTC/USDT", TradeStatus.MANUALLY_CLOSED)

    assert closed is not None
    assert closed.status == TradeStatus.MANUALLY_CLOSED
    assert not has_active_trade("BTC/USDT")


def test_close_nonexistent():
    result = close_trade("DOGE/USDT")
    assert result is None


# ── Update trades (with mocked price fetch) ─────────────────────────

@patch("trade_tracker.fetch_ohlcv")
def test_update_sends_periodic_update(mock_fetch):
    """After registering a trade and waiting past the update interval,
    update_trades should yield an 'update' event."""
    mock_df = pd.DataFrame({"close": [51000.0]})
    mock_fetch.return_value = mock_df

    sig = FakeSignal()
    trade = register_trade(sig)
    trade.last_update_sent = 0  # force update to be due

    updates = update_trades()

    assert len(updates) == 1
    assert updates[0]["event"] == "update"
    assert updates[0]["trade"].current_price == 51000.0


@patch("trade_tracker.fetch_ohlcv")
def test_update_detects_target_hit(mock_fetch):
    mock_df = pd.DataFrame({"close": [55000.0]})
    mock_fetch.return_value = mock_df

    register_trade(FakeSignal())
    updates = update_trades()

    assert len(updates) == 1
    assert updates[0]["event"] == "target_hit"
    assert not has_active_trade("BTC/USDT")


@patch("trade_tracker.fetch_ohlcv")
def test_update_detects_stop_loss(mock_fetch):
    mock_df = pd.DataFrame({"close": [47000.0]})
    mock_fetch.return_value = mock_df

    register_trade(FakeSignal())
    updates = update_trades()

    assert len(updates) == 1
    assert updates[0]["event"] == "stop_loss_hit"
    assert not has_active_trade("BTC/USDT")


# ── Duration string ──────────────────────────────────────────────────

def test_duration_string():
    trade = ActiveTrade(
        symbol="BTC/USDT", direction="BUY",
        entry_price=50000.0, stop_loss=48000.0, target=54000.0,
        confidence=0.85,
    )
    trade.opened_at = time.time() - 3665  # ~1h 1m
    dur = trade.duration_str
    assert "1h" in dur
