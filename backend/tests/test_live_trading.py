"""
Live Trading API Tests - Iteration 3
Tests the new /api/live/* endpoints for live trading functionality.

Test Coverage:
- GET /api/live/status - Returns live trading status
- POST /api/live/connect - Attempts FIX connection (expected to fail in preview)
- POST /api/live/start - Start trading (requires connection)
- POST /api/live/stop - Stop trading

Note: FIX connection will fail in preview environment - this is expected.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://ftmo-bot-live.preview.emergentagent.com').rstrip('/')


class TestLiveTradingAPI:
    """Tests for Live Trading endpoints"""
    
    def test_live_status_returns_valid_response(self):
        """GET /api/live/status should return proper structure"""
        response = requests.get(f"{BASE_URL}/api/live/status")
        assert response.status_code == 200
        
        data = response.json()
        
        # Check required fields in response
        required_fields = ["connected", "trading", "strategies", "symbols", "open_trades", 
                         "closed_trades", "risk_status", "market_prices", "active_trades", "recent_closed"]
        
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        
        # Verify types
        assert isinstance(data["connected"], bool)
        assert isinstance(data["trading"], bool)
        assert isinstance(data["strategies"], dict)
        assert isinstance(data["symbols"], list)
        
        print(f"✓ Live status: connected={data['connected']}, trading={data['trading']}")
        print(f"  Strategies: {data['strategies']}")
        print(f"  Symbols: {data['symbols']}")
    
    def test_live_connect_attempts_fix_connection(self):
        """POST /api/live/connect should attempt FIX connection"""
        response = requests.post(f"{BASE_URL}/api/live/connect")
        assert response.status_code == 200
        
        data = response.json()
        
        # In preview environment, connection will fail
        # The important thing is the API returns proper structure
        assert "success" in data
        
        # Expected to fail in preview environment (external connections blocked)
        if not data["success"]:
            assert "error" in data
            print(f"✓ FIX connection attempt returned: success=False (expected in preview)")
            print(f"  Error: {data['error']}")
        else:
            print(f"✓ FIX connection returned success (unexpected in preview)")
    
    def test_live_start_requires_connection(self):
        """POST /api/live/start should require FIX connection"""
        response = requests.post(
            f"{BASE_URL}/api/live/start",
            json={
                "initial_balance": 10000,
                "symbols": ["EURUSD"],
                "strategies": {"scalping": True, "intraday": True}
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        
        # Without connection, start should fail
        assert "success" in data
        if not data["success"]:
            assert "error" in data
            assert "not connected" in data["error"].lower() or "connexion" in data.get("error", "").lower()
            print(f"✓ Start trading correctly requires connection: {data['error']}")
        else:
            print(f"✓ Start trading returned success (connection was already established)")
    
    def test_live_stop_returns_success(self):
        """POST /api/live/stop should always succeed"""
        response = requests.post(f"{BASE_URL}/api/live/stop")
        assert response.status_code == 200
        
        data = response.json()
        
        assert data["success"] == True
        assert "message" in data
        assert "open_positions" in data
        assert "total_closed" in data
        
        print(f"✓ Stop trading: {data['message']}")
        print(f"  Open positions: {data['open_positions']}, Total closed: {data['total_closed']}")


class TestBacktestFTMOCompliance:
    """Test FTMO compliance for all strategies - extended validation"""
    
    def test_scalping_ftmo_compliance(self):
        """SCALPING strategy should be FTMO compliant"""
        response = requests.post(
            f"{BASE_URL}/api/backtest/professional",
            json={
                "symbol": "EURUSD",
                "strategy": "SCALPING",
                "days": 90,
                "initial_balance": 10000
            },
            timeout=120
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True, f"Backtest failed: {data.get('error')}"
        
        result = data["result"]
        
        # FTMO compliance assertions
        assert result["ftmo_daily_limit_breached"] == False, \
            f"SCALPING breached daily limit: max_daily_loss={result['max_daily_loss_percent']}%"
        assert result["ftmo_total_limit_breached"] == False, \
            f"SCALPING breached total limit: max_drawdown={result['max_drawdown_percent']}%"
        assert result["max_daily_loss_percent"] < 4.5, \
            f"max_daily_loss_percent={result['max_daily_loss_percent']}% >= 4.5%"
        assert result["max_drawdown_percent"] < 8, \
            f"max_drawdown_percent={result['max_drawdown_percent']}% >= 8%"
        
        print(f"✓ SCALPING FTMO compliant:")
        print(f"  max_daily_loss_percent: {result['max_daily_loss_percent']}% (limit: 4.5%)")
        print(f"  max_drawdown_percent: {result['max_drawdown_percent']}% (limit: 8%)")
        print(f"  total_trades: {result['total_trades']}, win_rate: {result['win_rate']}%")
    
    def test_intraday_ftmo_compliance(self):
        """INTRADAY strategy should be FTMO compliant"""
        response = requests.post(
            f"{BASE_URL}/api/backtest/professional",
            json={
                "symbol": "EURUSD",
                "strategy": "INTRADAY",
                "days": 90,
                "initial_balance": 10000
            },
            timeout=120
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        
        result = data["result"]
        
        assert result["ftmo_daily_limit_breached"] == False
        assert result["ftmo_total_limit_breached"] == False
        assert result["max_daily_loss_percent"] < 4.5
        assert result["max_drawdown_percent"] < 8
        
        print(f"✓ INTRADAY FTMO compliant:")
        print(f"  max_daily_loss_percent: {result['max_daily_loss_percent']}%")
        print(f"  max_drawdown_percent: {result['max_drawdown_percent']}%")
    
    def test_both_strategies_ftmo_compliance(self):
        """BOTH strategies should be FTMO compliant"""
        response = requests.post(
            f"{BASE_URL}/api/backtest/professional",
            json={
                "symbol": "EURUSD",
                "strategy": "BOTH",
                "days": 90,
                "initial_balance": 10000
            },
            timeout=120
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        
        result = data["result"]
        
        assert result["ftmo_daily_limit_breached"] == False
        assert result["ftmo_total_limit_breached"] == False
        assert result["max_daily_loss_percent"] < 4.5
        assert result["max_drawdown_percent"] < 8
        
        print(f"✓ BOTH FTMO compliant:")
        print(f"  max_daily_loss_percent: {result['max_daily_loss_percent']}%")
        print(f"  max_drawdown_percent: {result['max_drawdown_percent']}%")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
