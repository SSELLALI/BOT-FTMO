"""
Backend API Tests for FTMO Trading Bot
Tests all API endpoints for functionality and compliance
"""
import requests
import sys
import json
from datetime import datetime

class FTMOBotAPITester:
    def __init__(self, base_url="https://cbots-cloud.preview.emergentagent.com"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []
        self.passed_tests = []
        
    def log_result(self, test_name, success, details=""):
        """Log test results"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            self.passed_tests.append(test_name)
            print(f"✅ {test_name} - PASSED")
        else:
            self.failed_tests.append({"test": test_name, "details": details})
            print(f"❌ {test_name} - FAILED: {details}")
            
    def run_test(self, name, method, endpoint, expected_status=200, data=None, headers=None):
        """Run a single API test"""
        url = f"{self.api_url}/{endpoint}" if endpoint else f"{self.api_url}/"
        test_headers = {'Content-Type': 'application/json'}
        if headers:
            test_headers.update(headers)
            
        print(f"\n🔍 Testing {name}: {method} {endpoint}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=test_headers, timeout=10)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=test_headers, timeout=10)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=test_headers, timeout=10)
            else:
                self.log_result(name, False, f"Unsupported method: {method}")
                return False, {}
                
            success = response.status_code == expected_status
            
            if success:
                try:
                    response_data = response.json() if response.text else {}
                    print(f"   Status: {response.status_code} ✓")
                    if response_data and isinstance(response_data, dict):
                        if len(str(response_data)) > 200:
                            print(f"   Response: [Large response - {len(str(response_data))} chars]")
                        else:
                            print(f"   Response: {response_data}")
                    self.log_result(name, True)
                    return True, response_data
                except json.JSONDecodeError:
                    print(f"   Status: {response.status_code} ✓")
                    print(f"   Response: [Non-JSON response]")
                    self.log_result(name, True)
                    return True, {}
            else:
                error_msg = f"Expected {expected_status}, got {response.status_code}"
                try:
                    error_data = response.json() if response.text else response.text
                    error_msg += f" - {error_data}"
                except:
                    error_msg += f" - {response.text[:200]}..."
                self.log_result(name, False, error_msg)
                return False, {}
                
        except requests.exceptions.RequestException as e:
            self.log_result(name, False, f"Network error: {str(e)}")
            return False, {}
        except Exception as e:
            self.log_result(name, False, f"Unexpected error: {str(e)}")
            return False, {}
    
    def test_basic_endpoints(self):
        """Test basic API endpoints"""
        print("\n" + "="*50)
        print("TESTING BASIC API ENDPOINTS")
        print("="*50)
        
        # Test root API
        self.run_test("Root API Status", "GET", "")
        
        # Test dashboard
        success, dashboard_data = self.run_test("Dashboard Data", "GET", "dashboard")
        
        # Test settings
        self.run_test("Bot Settings", "GET", "settings")
        
        # Test connection status
        self.run_test("Connection Status", "GET", "connection/status")
        
        # Test risk status
        self.run_test("Risk Status", "GET", "risk/status")
        
        return dashboard_data
    
    def test_market_endpoints(self):
        """Test market data endpoints"""
        print("\n" + "="*50)
        print("TESTING MARKET DATA ENDPOINTS")
        print("="*50)
        
        # Test market quotes
        self.run_test("Market Quotes", "GET", "market/quotes")
        
        # Test specific symbol prices
        self.run_test("EURUSD Prices", "GET", "market/prices/EURUSD")
        
        # Test indicators
        self.run_test("EURUSD Indicators", "GET", "market/indicators/EURUSD")
        
    def test_trading_endpoints(self):
        """Test trading-related endpoints"""
        print("\n" + "="*50)
        print("TESTING TRADING ENDPOINTS")
        print("="*50)
        
        # Test trading signals
        self.run_test("Bot Signals", "GET", "bot/signals")
        
        # Test trades history
        self.run_test("Trades History", "GET", "trades")
        
        # Test open trades
        self.run_test("Open Trades", "GET", "trades/open")
        
        # Test stats
        self.run_test("Daily Stats", "GET", "stats/daily")
        self.run_test("Equity Curve", "GET", "stats/equity-curve")
        
    def test_bot_controls(self):
        """Test bot control endpoints"""
        print("\n" + "="*50)
        print("TESTING BOT CONTROL ENDPOINTS") 
        print("="*50)
        
        # Test bot start (should work)
        success, _ = self.run_test("Start Bot", "POST", "bot/start")
        
        if success:
            # Test bot stop
            self.run_test("Stop Bot", "POST", "bot/stop")
        
    def test_demo_data_generation(self):
        """Test demo data generation"""
        print("\n" + "="*50)
        print("TESTING DEMO DATA GENERATION")
        print("="*50)
        
        # Generate demo trades
        success, response = self.run_test("Generate Demo Trades", "POST", "demo/generate-trades")
        
        if success:
            # Verify trades were created by checking trades endpoint
            success2, trades_data = self.run_test("Verify Demo Trades", "GET", "trades?limit=5")
            if success2 and trades_data.get("count", 0) > 0:
                print(f"   ✓ Generated {trades_data.get('count')} demo trades")
            
    def test_risk_validation(self):
        """Test risk management validation"""
        print("\n" + "="*50)
        print("TESTING RISK MANAGEMENT")
        print("="*50)
        
        # Test risk validation with valid parameters
        params = "entry_price=1.0850&stop_loss=1.0840&take_profit=1.0865&lot_size=0.1&direction=BUY"
        self.run_test("Risk Validation (Valid)", "GET", f"risk/validate?{params}")
        
        # Test risk validation with invalid RR (too low)
        params2 = "entry_price=1.0850&stop_loss=1.0840&take_profit=1.0851&lot_size=0.1&direction=BUY"
        success, response = self.run_test("Risk Validation (Invalid RR)", "GET", f"risk/validate?{params2}")
        if success and response.get("valid") == False:
            print(f"   ✓ Correctly rejected trade with bad RR: {response.get('reason', '')}")
        
    def test_settings_update(self):
        """Test settings update functionality"""
        print("\n" + "="*50)
        print("TESTING SETTINGS UPDATE")
        print("="*50)
        
        # Test updating settings
        update_data = {
            "scalping_enabled": True,
            "intraday_enabled": True,
            "scalping_lot_size": 0.1,
            "intraday_lot_size": 0.05
        }
        
        success, response = self.run_test("Update Settings", "PUT", "settings", data=update_data)
        
        if success:
            # Verify settings were updated
            success2, settings = self.run_test("Verify Settings Update", "GET", "settings")
            if success2 and settings.get("scalping_enabled") == True:
                print("   ✓ Settings successfully updated")
    
    def test_manual_trade_creation(self):
        """Test manual trade creation"""
        print("\n" + "="*50)
        print("TESTING MANUAL TRADE CREATION")
        print("="*50)
        
        # Valid trade data
        trade_data = {
            "symbol": "EURUSD",
            "direction": "BUY", 
            "entry_price": 1.0850,
            "stop_loss": 1.0830,
            "take_profit": 1.0880,
            "lot_size": 0.1,
            "strategy": "MANUAL"
        }
        
        success, response = self.run_test("Create Valid Trade", "POST", "trades", data=trade_data)
        
        if success:
            # Try to get the created trade
            self.run_test("Verify Trade Creation", "GET", "trades?limit=1")
            
        # Test invalid trade (bad RR ratio)
        invalid_trade = {
            "symbol": "EURUSD", 
            "direction": "BUY",
            "entry_price": 1.0850,
            "stop_loss": 1.0840,
            "take_profit": 1.0851,  # Too small profit vs risk
            "lot_size": 0.1,
            "strategy": "MANUAL"
        }
        
        success, response = self.run_test("Create Invalid Trade", "POST", "trades", 
                                        expected_status=400, data=invalid_trade)
        if success:
            print("   ✓ Correctly rejected invalid trade")

    def run_comprehensive_test(self):
        """Run all tests"""
        print("🚀 Starting FTMO Trading Bot API Tests")
        print(f"Testing against: {self.api_url}")
        print("="*60)
        
        # Run all test suites
        dashboard_data = self.test_basic_endpoints()
        self.test_market_endpoints()
        self.test_trading_endpoints()
        self.test_bot_controls()
        self.test_demo_data_generation()
        self.test_risk_validation()
        self.test_settings_update()
        self.test_manual_trade_creation()
        
        # Print summary
        print("\n" + "="*60)
        print("📊 TEST SUMMARY")
        print("="*60)
        print(f"Total tests run: {self.tests_run}")
        print(f"Tests passed: {self.tests_passed}")
        print(f"Tests failed: {len(self.failed_tests)}")
        print(f"Success rate: {(self.tests_passed/self.tests_run*100):.1f}%")
        
        if self.failed_tests:
            print("\n❌ FAILED TESTS:")
            for failure in self.failed_tests:
                print(f"  - {failure['test']}: {failure['details']}")
        
        if self.passed_tests:
            print(f"\n✅ PASSED TESTS ({len(self.passed_tests)}):")
            for test in self.passed_tests:
                print(f"  - {test}")
        
        # Return overall success
        return len(self.failed_tests) == 0

def main():
    """Main test execution"""
    tester = FTMOBotAPITester()
    
    try:
        success = tester.run_comprehensive_test()
        return 0 if success else 1
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\n💥 Unexpected error during testing: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())