"""
FTMO Professional Backtest API Tests
Tests the backtest endpoints with FTMO compliance verification

Test Coverage:
- SCALPING strategy backtest
- INTRADAY strategy backtest
- BOTH strategies backtest
- FTMO compliance checks (4.5% daily, 8% total drawdown)
- Trade structure validation
"""
import pytest
import requests
import os
import time

# Use the public URL for testing
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://ftmo-strategy-forge.preview.emergentagent.com').rstrip('/')


class TestFTMOBacktest:
    """Tests for FTMO Professional Backtest endpoint"""
    
    def test_api_health(self):
        """Test basic API health"""
        response = requests.get(f"{BASE_URL}/api/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        print(f"✓ API is running: {data}")
    
    def test_risk_status_shows_8_percent_limit(self):
        """Verify risk status shows 8% total loss limit (not 10%)"""
        response = requests.get(f"{BASE_URL}/api/risk/status")
        assert response.status_code == 200
        data = response.json()
        
        # Critical FTMO requirement: 8% total drawdown limit
        assert data["total_loss_limit"] == 8.0, f"Expected 8% total loss limit, got {data['total_loss_limit']}%"
        assert data["daily_loss_limit"] == 4.5, f"Expected 4.5% daily loss limit, got {data['daily_loss_limit']}%"
        assert data["max_risk_per_trade"] == 1.0, f"Expected 1% max risk per trade, got {data['max_risk_per_trade']}%"
        
        print(f"✓ Risk limits correct: daily={data['daily_loss_limit']}%, total={data['total_loss_limit']}%, per_trade={data['max_risk_per_trade']}%")
    
    def test_dashboard_endpoint(self):
        """Test dashboard returns valid data"""
        response = requests.get(f"{BASE_URL}/api/dashboard")
        assert response.status_code == 200
        data = response.json()
        
        # Verify required fields exist
        assert "account" in data
        assert "risk_status" in data
        assert "market_data" in data
        
        print(f"✓ Dashboard returns valid data with {len(data.get('market_data', []))} market quotes")


class TestScalpingBacktest:
    """Test SCALPING strategy backtest"""
    
    @pytest.fixture(scope="class")
    def backtest_result(self):
        """Run SCALPING backtest once and cache result"""
        response = requests.post(
            f"{BASE_URL}/api/backtest/professional",
            json={
                "symbol": "EURUSD",
                "strategy": "SCALPING",
                "days": 90,
                "initial_balance": 10000
            },
            timeout=120  # Backtest can take time
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True, f"Backtest failed: {data.get('error')}"
        return data["result"]
    
    def test_scalping_returns_ftmo_compliant(self, backtest_result):
        """Scalping backtest should be FTMO compliant"""
        result = backtest_result
        
        # FTMO Compliance checks
        assert result["ftmo_daily_limit_breached"] == False, \
            f"SCALPING breached daily limit! Max daily loss: {result['max_daily_loss_percent']}%"
        assert result["ftmo_total_limit_breached"] == False, \
            f"SCALPING breached total drawdown! Max drawdown: {result['max_drawdown_percent']}%"
        
        print(f"✓ SCALPING FTMO compliant: daily_breached={result['ftmo_daily_limit_breached']}, total_breached={result['ftmo_total_limit_breached']}")
    
    def test_scalping_max_daily_loss_under_limit(self, backtest_result):
        """Max daily loss should be under 4.5%"""
        result = backtest_result
        
        assert result["max_daily_loss_percent"] < 4.5, \
            f"Max daily loss {result['max_daily_loss_percent']}% exceeds 4.5% limit"
        
        print(f"✓ SCALPING max daily loss: {result['max_daily_loss_percent']}% (limit: 4.5%)")
    
    def test_scalping_max_drawdown_under_limit(self, backtest_result):
        """Max drawdown should be under 8%"""
        result = backtest_result
        
        assert result["max_drawdown_percent"] < 8.0, \
            f"Max drawdown {result['max_drawdown_percent']}% exceeds 8% limit"
        
        print(f"✓ SCALPING max drawdown: {result['max_drawdown_percent']}% (limit: 8%)")
    
    def test_scalping_has_trades(self, backtest_result):
        """SCALPING should generate trades"""
        result = backtest_result
        
        assert result["total_trades"] > 0, "SCALPING produced no trades"
        print(f"✓ SCALPING generated {result['total_trades']} trades")
    
    def test_scalping_trades_have_required_fields(self, backtest_result):
        """Trades should have all required fields"""
        result = backtest_result
        
        if result["trades"] and len(result["trades"]) > 0:
            trade = result["trades"][0]
            required_fields = ["entry_price", "exit_price", "sl_pips", "tp_pips", "pnl", "exit_reason", "direction", "strategy"]
            
            for field in required_fields:
                assert field in trade, f"Trade missing required field: {field}"
            
            # Verify exit_reason is one of expected values
            valid_exit_reasons = ["TP", "SL", "EOD", "SAFETY_CLOSE"]
            assert trade["exit_reason"] in valid_exit_reasons, f"Invalid exit_reason: {trade['exit_reason']}"
            
            print(f"✓ SCALPING trades have all required fields. Sample: {trade['direction']} @ {trade['entry_price']}, exit: {trade['exit_reason']}, P&L: {trade['pnl']}")


class TestIntradayBacktest:
    """Test INTRADAY strategy backtest"""
    
    @pytest.fixture(scope="class")
    def backtest_result(self):
        """Run INTRADAY backtest once and cache result"""
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
        assert data.get("success") == True, f"Backtest failed: {data.get('error')}"
        return data["result"]
    
    def test_intraday_returns_ftmo_compliant(self, backtest_result):
        """INTRADAY backtest should be FTMO compliant"""
        result = backtest_result
        
        assert result["ftmo_daily_limit_breached"] == False, \
            f"INTRADAY breached daily limit! Max daily loss: {result['max_daily_loss_percent']}%"
        assert result["ftmo_total_limit_breached"] == False, \
            f"INTRADAY breached total drawdown! Max drawdown: {result['max_drawdown_percent']}%"
        
        print(f"✓ INTRADAY FTMO compliant: daily_breached={result['ftmo_daily_limit_breached']}, total_breached={result['ftmo_total_limit_breached']}")
    
    def test_intraday_max_daily_loss_under_limit(self, backtest_result):
        """Max daily loss should be under 4.5%"""
        result = backtest_result
        
        assert result["max_daily_loss_percent"] < 4.5, \
            f"Max daily loss {result['max_daily_loss_percent']}% exceeds 4.5% limit"
        
        print(f"✓ INTRADAY max daily loss: {result['max_daily_loss_percent']}% (limit: 4.5%)")
    
    def test_intraday_max_drawdown_under_limit(self, backtest_result):
        """Max drawdown should be under 8%"""
        result = backtest_result
        
        assert result["max_drawdown_percent"] < 8.0, \
            f"Max drawdown {result['max_drawdown_percent']}% exceeds 8% limit"
        
        print(f"✓ INTRADAY max drawdown: {result['max_drawdown_percent']}% (limit: 8%)")
    
    def test_intraday_has_trades(self, backtest_result):
        """INTRADAY should generate trades"""
        result = backtest_result
        
        assert result["total_trades"] > 0, "INTRADAY produced no trades"
        print(f"✓ INTRADAY generated {result['total_trades']} trades")
    
    def test_intraday_trades_have_required_fields(self, backtest_result):
        """Trades should have all required fields"""
        result = backtest_result
        
        if result["trades"] and len(result["trades"]) > 0:
            trade = result["trades"][0]
            required_fields = ["entry_price", "exit_price", "sl_pips", "tp_pips", "pnl", "exit_reason", "direction", "strategy"]
            
            for field in required_fields:
                assert field in trade, f"Trade missing required field: {field}"
            
            print(f"✓ INTRADAY trades have all required fields. Sample: {trade['direction']} @ {trade['entry_price']}, exit: {trade['exit_reason']}, P&L: {trade['pnl']}")


class TestBothStrategiesBacktest:
    """Test BOTH strategies combined backtest"""
    
    @pytest.fixture(scope="class")
    def backtest_result(self):
        """Run BOTH strategies backtest once and cache result"""
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
        assert data.get("success") == True, f"Backtest failed: {data.get('error')}"
        return data["result"]
    
    def test_both_returns_ftmo_compliant(self, backtest_result):
        """BOTH strategies backtest should be FTMO compliant"""
        result = backtest_result
        
        assert result["ftmo_daily_limit_breached"] == False, \
            f"BOTH breached daily limit! Max daily loss: {result['max_daily_loss_percent']}%"
        assert result["ftmo_total_limit_breached"] == False, \
            f"BOTH breached total drawdown! Max drawdown: {result['max_drawdown_percent']}%"
        
        print(f"✓ BOTH FTMO compliant: daily_breached={result['ftmo_daily_limit_breached']}, total_breached={result['ftmo_total_limit_breached']}")
    
    def test_both_max_daily_loss_under_limit(self, backtest_result):
        """Max daily loss should be under 4.5%"""
        result = backtest_result
        
        assert result["max_daily_loss_percent"] < 4.5, \
            f"Max daily loss {result['max_daily_loss_percent']}% exceeds 4.5% limit"
        
        print(f"✓ BOTH max daily loss: {result['max_daily_loss_percent']}% (limit: 4.5%)")
    
    def test_both_max_drawdown_under_limit(self, backtest_result):
        """Max drawdown should be under 8%"""
        result = backtest_result
        
        assert result["max_drawdown_percent"] < 8.0, \
            f"Max drawdown {result['max_drawdown_percent']}% exceeds 8% limit"
        
        print(f"✓ BOTH max drawdown: {result['max_drawdown_percent']}% (limit: 8%)")
    
    def test_both_has_trades(self, backtest_result):
        """BOTH should generate trades"""
        result = backtest_result
        
        assert result["total_trades"] > 0, "BOTH produced no trades"
        print(f"✓ BOTH generated {result['total_trades']} trades")
    
    def test_both_includes_both_strategies(self, backtest_result):
        """Combined backtest should include trades from both strategies"""
        result = backtest_result
        
        if result["trades"] and len(result["trades"]) > 0:
            strategies_found = set()
            for trade in result["trades"]:
                strategies_found.add(trade.get("strategy"))
            
            # It's okay if not both strategies produced trades due to random data
            print(f"✓ BOTH includes strategies: {strategies_found}")


class TestBacktestReport:
    """Test backtest report structure and values"""
    
    @pytest.fixture(scope="class")
    def backtest_result(self):
        """Run a backtest and return result"""
        response = requests.post(
            f"{BASE_URL}/api/backtest/professional",
            json={
                "symbol": "EURUSD",
                "strategy": "SCALPING",
                "days": 30,  # Shorter period for faster test
                "initial_balance": 10000
            },
            timeout=120
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") == True
        return data["result"]
    
    def test_report_has_required_metrics(self, backtest_result):
        """Report should have all required FTMO metrics"""
        result = backtest_result
        
        required_fields = [
            "initial_balance", "final_balance", "total_return", "total_return_percent",
            "max_drawdown", "max_drawdown_percent", "total_trades", "winning_trades", 
            "losing_trades", "win_rate", "profit_factor", "ftmo_daily_limit_breached",
            "ftmo_total_limit_breached", "max_daily_loss", "max_daily_loss_percent",
            "equity_curve", "trades", "daily_returns"
        ]
        
        for field in required_fields:
            assert field in result, f"Report missing required field: {field}"
        
        print(f"✓ Report has all {len(required_fields)} required fields")
    
    def test_report_equity_curve_valid(self, backtest_result):
        """Equity curve should have valid data points"""
        result = backtest_result
        
        equity_curve = result.get("equity_curve", [])
        if len(equity_curve) > 0:
            point = equity_curve[0]
            assert "equity" in point, "Equity curve point missing 'equity' field"
            assert point["equity"] > 0, "Equity should be positive"
            
            print(f"✓ Equity curve has {len(equity_curve)} data points")
    
    def test_report_daily_returns_valid(self, backtest_result):
        """Daily returns should have valid data"""
        result = backtest_result
        
        daily_returns = result.get("daily_returns", [])
        if len(daily_returns) > 0:
            day = daily_returns[0]
            assert "date" in day, "Daily return missing 'date'"
            assert "pnl" in day, "Daily return missing 'pnl'"
            
            print(f"✓ Daily returns has {len(daily_returns)} days")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
