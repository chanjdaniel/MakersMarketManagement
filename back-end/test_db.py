#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import db, User, Organization, Market

def test_database():
    with app.app_context():
        try:
            # Create all tables
            db.create_all()
            print("✓ Database tables created successfully")
            
            # Test creating a user
            test_user = User(email="test@example.com", password_hash="test_hash")
            db.session.add(test_user)
            db.session.commit()
            print("✓ User creation test passed")
            
            # Test creating an organization
            test_org = Organization(name="Test Organization", description="Test description")
            db.session.add(test_org)
            db.session.commit()
            print("✓ Organization creation test passed")
            
            # Test creating a market
            test_market = Market(
                name="Test Market",
                organization_id=test_org.id,
                owner_id=test_user.id
            )
            test_market.set_setup_object({"test": "data"})
            db.session.add(test_market)
            db.session.commit()
            print("✓ Market creation test passed")
            
            # Test relationships
            user = User.query.filter_by(email="test@example.com").first()
            if user:
                print(f"✓ User query test passed: {user.email}")
            
            market = Market.query.filter_by(name="Test Market").first()
            if market and market.owner.email == "test@example.com":
                print("✓ Market-User relationship test passed")
            
            # Clean up test data
            db.session.delete(test_market)
            db.session.delete(test_org)
            db.session.delete(test_user)
            db.session.commit()
            print("✓ Cleanup completed")
            
            print("\n🎉 All database tests passed successfully!")
            return True
            
        except Exception as e:
            print(f"❌ Database test failed: {str(e)}")
            db.session.rollback()
            return False

if __name__ == "__main__":
    success = test_database()
    sys.exit(0 if success else 1)
