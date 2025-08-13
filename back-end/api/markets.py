from flask import request, jsonify
from models import db, User, Market, Organization
from sqlalchemy.exc import IntegrityError

def load_market_request(current_user, request):
    data = request.json
    name = data.get("name")

    if not name:
        return jsonify({"msg": "Market name required"}), 400

    # Find market by name
    market = Market.query.filter_by(name=name).first()
    if not market:
        return jsonify({"msg": "Market not found"}), 404

    # Check if user has permission to view this market
    if not market.user_can_view(current_user):
        return jsonify({"msg": "Unauthorized user"}), 401

    return jsonify({"msg": "Market successfully loaded", "market": market.to_dict()}), 200

def save_market_request(current_user, request):
    data = request.json
    new_market_dict = data.get("market")

    if not new_market_dict:
        return jsonify({"msg": "Invalid market input"}), 400

    market_name = new_market_dict.get("name")
    if not market_name:
        return jsonify({"msg": "Market name required"}), 400

    try:
        # Check if market exists
        existing_market = Market.query.filter_by(name=market_name).first()
        
        if existing_market:
            # Update existing market
            if not existing_market.user_can_edit(current_user):
                return jsonify({"msg": f"Unauthorized user: {current_user.email}"}), 401
            
            # Update market fields
            existing_market.set_setup_object(new_market_dict.get("setupObject"))
            existing_market.set_modification_list(new_market_dict.get("modificationList", []))
            existing_market.set_assignment_object(new_market_dict.get("assignmentObject"))
            
            # Update editors and viewers if provided
            if "editors" in new_market_dict:
                existing_market.editors.clear()
                for editor_email in new_market_dict["editors"]:
                    editor_user = User.query.filter_by(email=editor_email).first()
                    if editor_user:
                        existing_market.editors.append(editor_user)
            
            if "viewers" in new_market_dict:
                existing_market.viewers.clear()
                for viewer_email in new_market_dict["viewers"]:
                    viewer_user = User.query.filter_by(email=viewer_email).first()
                    if viewer_user:
                        existing_market.viewers.append(viewer_user)
            
            db.session.commit()
            return jsonify({"msg": "Market successfully updated"}), 200
        
        else:
            # Create new market
            # For now, assume organization_id = 1 (we'll improve this in the next task)
            organization = Organization.query.first()
            if not organization:
                # Create a default organization if none exists
                organization = Organization(name="Default Organization", description="Default organization for markets")
                db.session.add(organization)
                db.session.flush()  # Get the ID
            
            new_market = Market(
                name=market_name,
                organization_id=organization.id,
                owner_id=current_user.id
            )
            
            new_market.set_setup_object(new_market_dict.get("setupObject"))
            new_market.set_modification_list(new_market_dict.get("modificationList", []))
            new_market.set_assignment_object(new_market_dict.get("assignmentObject"))
            
            db.session.add(new_market)
            db.session.flush()  # Get the market ID
            
            # Add editors and viewers
            if "editors" in new_market_dict:
                for editor_email in new_market_dict["editors"]:
                    editor_user = User.query.filter_by(email=editor_email).first()
                    if editor_user:
                        new_market.editors.append(editor_user)
            
            if "viewers" in new_market_dict:
                for viewer_email in new_market_dict["viewers"]:
                    viewer_user = User.query.filter_by(email=viewer_email).first()
                    if viewer_user:
                        new_market.viewers.append(viewer_user)
            
            db.session.commit()
            return jsonify({"msg": "Market successfully created"}), 201
    
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": f"Failed to save market: {str(e)}"}), 500


