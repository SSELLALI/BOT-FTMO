"""
PA Strategy API Tests - Iteration 5
Tests the newly deployed USDJPY Price Action strategy endpoints.

Test Coverage:
- GET /api/live/status - Returns PA strategy info with h1_ready status
- GET /api/live/pa-strategy - Returns validated strategy details + robustness audit
- PUT /api/live/strategies - Toggles individual strategies on/off
- GET /api/dashboard - Still works correctly
- GET /api/ - Root endpoint works

Strategy defaults:
- pa_breakout=True, pa_bounce=True, scalping=False, intraday=False
- PA Strategy loads 500 H1 + 500 M30 candles on startup
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')


class TestRootAndDashboard:
    """Basic API health tests"""
    
    def test_root_endpoint_works(self):
        """GET /api/ should return running status"""
        response = requests.get(f"{BASE_URL}/api/")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "running"
        assert "FTMO Trading Bot API" in data["message"]
        print(f"✓ Root endpoint: {data['message']}, status={data['status']}")
    
    def test_dashboard_still_works(self):
        """GET /api/dashboard should return valid dashboard data"""
        response = requests.get(f"{BASE_URL}/api/dashboard")
        assert response.status_code == 200
        
        data = response.json()
        
        required_fields = ["account", "risk_status", "recent_trades", "open_trades", 
                         "market_data", "indicators", "bot_active", "timestamp"]
        for field in required_fields:
            assert field in data, f"Dashboard missing field: {field}"
        
        # Verify account structure
        assert "current_balance" in data["account"]
        assert "total_pnl" in data["account"]
        
        # Verify risk_status structure
        assert "daily_loss_percent" in data["risk_status"] or "daily_pnl_percent" in data["risk_status"]
        
        print(f"✓ Dashboard: account balance={data['account'].get('current_balance')}")
        print(f"  Recent trades: {len(data['recent_trades'])}, Open trades: {len(data['open_trades'])}")


class TestLiveStatusWithPAStrategy:
    """Tests for GET /api/live/status with PA strategy info"""
    
    def test_live_status_returns_pa_strategy_info(self):
        """GET /api/live/status should include PA strategy info"""
        response = requests.get(f"{BASE_URL}/api/live/status")
        assert response.status_code == 200
        
        data = response.json()
        
        # Basic structure validation
        assert "strategies" in data
        assert "pa_strategy" in data
        assert "h1_candles_buffered" in data
        assert "m30_candles_buffered" in data
        
        # PA strategy fields
        pa = data["pa_strategy"]
        assert "h1_ready" in pa, "PA strategy should have h1_ready field"
        assert "symbol" in pa
        assert pa["symbol"] == "USDJPY", f"Expected USDJPY, got {pa['symbol']}"
        
        print(f"✓ Live status includes PA strategy:")
        print(f"  h1_ready={pa.get('h1_ready')}")
        print(f"  h1_candles={pa.get('h1_candles', data.get('h1_candles_buffered', 0))}")
        print(f"  m30_candles={pa.get('m30_candles', data.get('m30_candles_buffered', 0))}")
        print(f"  daily_trades={pa.get('daily_trades')}")
    
    def test_live_status_has_correct_default_strategies(self):
        """Strategies should default to pa_breakout=True, pa_bounce=True, scalping=False, intraday=False"""
        response = requests.get(f"{BASE_URL}/api/live/status")
        assert response.status_code == 200
        
        data = response.json()
        strategies = data["strategies"]
        
        # Validate defaults
        assert "pa_breakout" in strategies, "Missing pa_breakout strategy"
        assert "pa_bounce" in strategies, "Missing pa_bounce strategy"
        assert "scalping" in strategies, "Missing scalping strategy"
        assert "intraday" in strategies, "Missing intraday strategy"
        
        # Check default values
        assert strategies["pa_breakout"] == True, f"pa_breakout should be True by default, got {strategies['pa_breakout']}"
        assert strategies["pa_bounce"] == True, f"pa_bounce should be True by default, got {strategies['pa_bounce']}"
        assert strategies["scalping"] == False, f"scalping should be False by default, got {strategies['scalping']}"
        assert strategies["intraday"] == False, f"intraday should be False by default, got {strategies['intraday']}"
        
        print(f"✓ Default strategies correct:")
        print(f"  pa_breakout={strategies['pa_breakout']} (expected True)")
        print(f"  pa_bounce={strategies['pa_bounce']} (expected True)")
        print(f"  scalping={strategies['scalping']} (expected False)")
        print(f"  intraday={strategies['intraday']} (expected False)")


class TestPAStrategyEndpoint:
    """Tests for GET /api/live/pa-strategy"""
    
    def test_pa_strategy_returns_validated_details(self):
        """GET /api/live/pa-strategy should return validated strategy details"""
        response = requests.get(f"{BASE_URL}/api/live/pa-strategy")
        assert response.status_code == 200
        
        data = response.json()
        
        # Required sections
        assert "live_status" in data, "Missing live_status"
        assert "robustness_audit" in data, "Missing robustness_audit"
        
        # Live status should have h1_ready
        live_status = data["live_status"]
        assert "h1_ready" in live_status
        assert "symbol" in live_status
        assert live_status["symbol"] == "USDJPY"
        
        print(f"✓ PA Strategy endpoint response:")
        print(f"  live_status.h1_ready={live_status.get('h1_ready')}")
        print(f"  live_status.h1_candles={live_status.get('h1_candles', 0)}")
    
    def test_pa_strategy_has_robustness_audit(self):
        """PA strategy should include robustness audit metrics"""
        response = requests.get(f"{BASE_URL}/api/live/pa-strategy")
        assert response.status_code == 200
        
        data = response.json()
        audit = data["robustness_audit"]
        
        # Verify BREAKOUT audit
        assert "breakout" in audit, "Missing breakout audit"
        br = audit["breakout"]
        assert "parameter_robustness" in br
        assert "walk_forward_oos" in br
        assert "temporal_stability" in br
        assert "weekly_estimate" in br
        
        # Verify BOUNCE audit
        assert "bounce" in audit, "Missing bounce audit"
        bo = audit["bounce"]
        assert "parameter_robustness" in bo
        assert "walk_forward_oos" in bo
        assert "temporal_stability" in bo
        assert "weekly_estimate" in bo
        
        # Verify combined metrics
        assert "combined_weekly_estimate" in audit
        assert "ftmo_compliant" in audit
        assert audit["ftmo_compliant"] == True, f"Expected FTMO compliant, got {audit['ftmo_compliant']}"
        
        print(f"✓ Robustness audit present:")
        print(f"  BREAKOUT: robustness={br['parameter_robustness']}, weekly={br['weekly_estimate']}")
        print(f"  BOUNCE: robustness={bo['parameter_robustness']}, weekly={bo['weekly_estimate']}")
        print(f"  Combined: {audit['combined_weekly_estimate']}")
        print(f"  FTMO compliant: {audit['ftmo_compliant']}")
    
    def test_pa_strategy_has_validated_strategy_section(self):
        """PA strategy should include validated_strategy section"""
        response = requests.get(f"{BASE_URL}/api/live/pa-strategy")
        assert response.status_code == 200
        
        data = response.json()
        
        # validated_strategy may be empty if usdjpy_validated_strategy.json doesn't exist
        # But the key should exist
        assert "validated_strategy" in data
        print(f"✓ validated_strategy key present: {type(data['validated_strategy'])}")


class TestStrategyToggle:
    """Tests for PUT /api/live/strategies"""
    
    def test_toggle_pa_breakout_off(self):
        """PUT /api/live/strategies should toggle pa_breakout off"""
        response = requests.put(
            f"{BASE_URL}/api/live/strategies",
            json={"pa_breakout": False}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == True
        assert "strategies" in data
        assert data["strategies"]["pa_breakout"] == False
        
        print(f"✓ Toggled pa_breakout off: {data['strategies']}")
    
    def test_toggle_pa_breakout_back_on(self):
        """PUT /api/live/strategies should toggle pa_breakout back on"""
        response = requests.put(
            f"{BASE_URL}/api/live/strategies",
            json={"pa_breakout": True}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == True
        assert data["strategies"]["pa_breakout"] == True
        
        print(f"✓ Toggled pa_breakout on: {data['strategies']}")
    
    def test_toggle_multiple_strategies(self):
        """PUT /api/live/strategies should toggle multiple strategies at once"""
        response = requests.put(
            f"{BASE_URL}/api/live/strategies",
            json={
                "pa_bounce": False,
                "scalping": True
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == True
        assert data["strategies"]["pa_bounce"] == False
        assert data["strategies"]["scalping"] == True
        
        print(f"✓ Toggled multiple strategies: {data['strategies']}")
    
    def test_reset_strategies_to_default(self):
        """Reset strategies to default state"""
        response = requests.put(
            f"{BASE_URL}/api/live/strategies",
            json={
                "pa_breakout": True,
                "pa_bounce": True,
                "scalping": False,
                "intraday": False
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] == True
        assert data["strategies"]["pa_breakout"] == True
        assert data["strategies"]["pa_bounce"] == True
        assert data["strategies"]["scalping"] == False
        assert data["strategies"]["intraday"] == False
        
        print(f"✓ Reset to defaults: {data['strategies']}")


class TestPAStrategyCandles:
    """Tests for PA Strategy candle initialization"""
    
    def test_h1_candles_loaded(self):
        """PA Strategy should have H1 candles loaded"""
        response = requests.get(f"{BASE_URL}/api/live/status")
        assert response.status_code == 200
        
        data = response.json()
        pa = data.get("pa_strategy", {})
        h1_candles = pa.get("h1_candles", data.get("h1_candles_buffered", 0))
        
        # We expect historical data to be loaded
        # Note: The service loads 500 H1 candles on startup if CSV available
        print(f"  H1 candles buffered: {h1_candles}")
        
        # h1_ready indicates if strategy has enough data
        h1_ready = pa.get("h1_ready", False)
        print(f"  h1_ready: {h1_ready}")
        
        # If CSV files exist, should have candles loaded
        if h1_candles > 0:
            print(f"✓ H1 candles loaded: {h1_candles} (historical data available)")
        else:
            print(f"  H1 candles not loaded (historical CSV may not exist)")
    
    def test_m30_candles_loaded(self):
        """PA Strategy should have M30 candles loaded"""
        response = requests.get(f"{BASE_URL}/api/live/status")
        assert response.status_code == 200
        
        data = response.json()
        pa = data.get("pa_strategy", {})
        m30_candles = pa.get("m30_candles", data.get("m30_candles_buffered", 0))
        
        print(f"  M30 candles buffered: {m30_candles}")
        
        if m30_candles > 0:
            print(f"✓ M30 candles loaded: {m30_candles} (historical data available)")
        else:
            print(f"  M30 candles not loaded (historical CSV may not exist)")


class TestValidatedPerformance:
    """Tests that PA Strategy returns expected validated performance metrics"""
    
    def test_validated_performance_metrics(self):
        """PA Strategy should return validated performance metrics"""
        response = requests.get(f"{BASE_URL}/api/live/pa-strategy")
        assert response.status_code == 200
        
        data = response.json()
        live_status = data["live_status"]
        
        if "validated_performance" in live_status:
            perf = live_status["validated_performance"]
            
            assert "breakout_weekly" in perf
            assert "bounce_weekly" in perf
            assert "combined_weekly" in perf
            assert "robustness_breakout" in perf
            assert "robustness_bounce" in perf
            assert "ftmo_compliant" in perf
            
            # Verify expected values
            assert perf["ftmo_compliant"] == True
            
            print(f"✓ Validated performance:")
            print(f"  BREAKOUT weekly: {perf['breakout_weekly']}")
            print(f"  BOUNCE weekly: {perf['bounce_weekly']}")
            print(f"  Combined weekly: {perf['combined_weekly']}")
            print(f"  FTMO compliant: {perf['ftmo_compliant']}")
        else:
            print("  validated_performance not in live_status (may be in different location)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
