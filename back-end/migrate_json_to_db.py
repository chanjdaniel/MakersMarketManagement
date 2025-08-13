#!/usr/bin/env python3
"""
Migration script to convert existing JSON data to SQLite database
"""

import sys
import os
import json
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import db, User, Organization, Market
from flask_bcrypt import Bcrypt

def migrate_json_data():
    """Migrate existing JSON data to SQLite database"""
    
    with app.app_context():
        bcrypt = Bcrypt()
        
        try:
            # Create all tables
            db.create_all()
            print("✓ Database tables created")
            
            # Create default organization if none exists
            default_org = Organization.query.first()
            if not default_org:
                default_org = Organization(
                    name="Default Organization",
                    description="Default organization for migrated data"
                )
                db.session.add(default_org)
                db.session.commit()
                print("✓ Default organization created")
            
            # Migrate users from JSON if file exists
            users_file = "./data/users.json"
            if os.path.exists(users_file):
                print(f"📁 Found users file: {users_file}")
                
                with open(users_file, 'r') as f:
                    users_data = json.load(f)
                
                migrated_users = 0
                for email, user_data in users_data.items():
                    # Check if user already exists
                    existing_user = User.query.filter_by(email=email).first()
                    if not existing_user:
                        new_user = User(
                            email=user_data["email"],
                            password_hash=user_data["password"]  # Already hashed
                        )
                        db.session.add(new_user)
                        migrated_users += 1
                
                db.session.commit()
                print(f"✓ Migrated {migrated_users} users from JSON")
            else:
                print("ℹ️  No users.json file found - skipping user migration")
            
            # Migrate markets from JSON if file exists
            markets_file = "./data/markets.json"
            if os.path.exists(markets_file):
                print(f"📁 Found markets file: {markets_file}")
                
                with open(markets_file, 'r') as f:
                    markets_data = json.load(f)
                
                migrated_markets = 0
                for market_name, market_data in markets_data.items():
                    # Check if market already exists
                    existing_market = Market.query.filter_by(name=market_name).first()
                    if not existing_market:
                        # Find owner user
                        owner_user = User.query.filter_by(email=market_data["owner"]).first()
                        if not owner_user:
                            # Create a placeholder user if owner doesn't exist
                            owner_user = User(
                                email=market_data["owner"],
                                password_hash=bcrypt.generate_password_hash("temp_password").decode('utf-8')
                            )
                            db.session.add(owner_user)
                            db.session.flush()  # Get the user ID
                        
                        new_market = Market(
                            name=market_data["name"],
                            organization_id=default_org.id,
                            owner_id=owner_user.id
                        )
                        
                        # Set JSON data
                        new_market.set_setup_object(market_data.get("setupObject"))
                        new_market.set_modification_list(market_data.get("modificationList", []))
                        new_market.set_assignment_object(market_data.get("assignmentObject"))
                        
                        db.session.add(new_market)
                        db.session.flush()  # Get the market ID
                        
                        # Add editors and viewers
                        for editor_email in market_data.get("editors", []):
                            editor_user = User.query.filter_by(email=editor_email).first()
                            if editor_user:
                                new_market.editors.append(editor_user)
                        
                        for viewer_email in market_data.get("viewers", []):
                            viewer_user = User.query.filter_by(email=viewer_email).first()
                            if viewer_user:
                                new_market.viewers.append(viewer_user)
                        
                        migrated_markets += 1
                
                db.session.commit()
                print(f"✓ Migrated {migrated_markets} markets from JSON")
            else:
                print("ℹ️  No markets.json file found - skipping market migration")
            
            # Create backup of JSON files
            if os.path.exists(users_file):
                backup_file = f"{users_file}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                os.rename(users_file, backup_file)
                print(f"✓ Backed up users.json to {backup_file}")
            
            if os.path.exists(markets_file):
                backup_file = f"{markets_file}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                os.rename(markets_file, backup_file)
                print(f"✓ Backed up markets.json to {backup_file}")
            
            print("\n🎉 Migration completed successfully!")
            return True
            
        except Exception as e:
            print(f"❌ Migration failed: {str(e)}")
            db.session.rollback()
            return False

if __name__ == "__main__":
    success = migrate_json_data()
    sys.exit(0 if success else 1)
