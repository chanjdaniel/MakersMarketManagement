#!/usr/bin/env python3
"""
Test script to verify that all migrated API functions work correctly with the new database
"""

import sys
import os
import json
from flask import Flask
from flask_bcrypt import Bcrypt

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import db, User, Organization, Market
import api.users as UsersApi
import api.markets as MarketsApi

class MockRequest:
    def __init__(self, json_data):
        self.json = json_data

def test_api_migration():
    """Test all migrated API functions"""
    
    with app.app_context():
        bcrypt = Bcrypt(app)
        
        try:
            # Clean up any existing test data
            test_user = User.query.filter_by(email="test_api@example.com").first()
            if test_user:
                db.session.delete(test_user)
            
            test_market = Market.query.filter_by(name="Test API Market").first()
            if test_market:
                db.session.delete(test_market)
            
            db.session.commit()
            
            print("🧪 Testing API Migration...")
            
            # Test 1: User Registration
            print("\n1. Testing User Registration API...")
            register_request = MockRequest({
                "email": "test_api@example.com",
                "password": "testpassword123",
                "organizations": [],
                "markets": []
            })
            
            response, status_code = UsersApi.register_user(bcrypt, register_request)
            response_data = json.loads(response.data)
            
            if status_code == 201 and response_data["msg"] == "User registered successfully":
                print("✓ User registration API test passed")
            else:
                print(f"❌ User registration API test failed: {response_data}")
                return False
            
            # Test 2: User Login
            print("\n2. Testing User Login API...")
            login_request = MockRequest({
                "email": "test_api@example.com",
                "password": "testpassword123"
            })
            
            # Mock login_user function
            def mock_login_user(user, remember=True):
                pass
            
            response, status_code = UsersApi.login(bcrypt, mock_login_user, login_request)
            response_data = json.loads(response.data)
            
            if status_code == 200 and response_data["message"] == "Login successful":
                print("✓ User login API test passed")
            else:
                print(f"❌ User login API test failed: {response_data}")
                return False
            
            # Test 3: Market Save
            print("\n3. Testing Market Save API...")
            test_user = User.query.filter_by(email="test_api@example.com").first()
            
            save_request = MockRequest({
                "market": {
                    "name": "Test API Market",
                    "owner": "test_api@example.com",
                    "editors": ["test_api@example.com"],
                    "viewers": ["test_api@example.com"],
                    "setupObject": {"test": "setup_data"},
                    "modificationList": [],
                    "assignmentObject": None
                }
            })
            
            response, status_code = MarketsApi.save_market_request(test_user, save_request)
            response_data = json.loads(response.data)
            
            if status_code == 201 and "successfully created" in response_data["msg"]:
                print("✓ Market save API test passed")
            else:
                print(f"❌ Market save API test failed: {response_data}")
                return False
            
            # Test 4: Market Load
            print("\n4. Testing Market Load API...")
            load_request = MockRequest({
                "name": "Test API Market"
            })
            
            response, status_code = MarketsApi.load_market_request(test_user, load_request)
            response_data = json.loads(response.data)
            
            if status_code == 200 and response_data["msg"] == "Market successfully loaded":
                print("✓ Market load API test passed")
                
                # Verify market data structure
                market_data = response_data["market"]
                if (market_data["name"] == "Test API Market" and 
                    market_data["setupObject"]["test"] == "setup_data"):
                    print("✓ Market data structure test passed")
                else:
                    print("❌ Market data structure test failed")
                    return False
            else:
                print(f"❌ Market load API test failed: {response_data}")
                return False
            
            # Test 5: Database Relationships
            print("\n5. Testing Database Relationships...")
            market = Market.query.filter_by(name="Test API Market").first()
            if market and market.owner.email == "test_api@example.com":
                print("✓ Market-User relationship test passed")
            else:
                print("❌ Market-User relationship test failed")
                return False
            
            # Test 6: JSON Serialization/Deserialization
            print("\n6. Testing JSON Data Handling...")
            setup_obj = market.get_setup_object()
            if setup_obj and setup_obj.get("test") == "setup_data":
                print("✓ JSON serialization/deserialization test passed")
            else:
                print("❌ JSON serialization/deserialization test failed")
                return False
            
            # Clean up test data
            db.session.delete(market)
            db.session.delete(test_user)
            db.session.commit()
            print("✓ Test cleanup completed")
            
            print("\n🎉 All API migration tests passed successfully!")
            print("✅ Database migration from JSON to SQLite is complete and functional!")
            return True
            
        except Exception as e:
            print(f"❌ API migration test failed: {str(e)}")
            db.session.rollback()
            return False

if __name__ == "__main__":
    success = test_api_migration()
    sys.exit(0 if success else 1)
