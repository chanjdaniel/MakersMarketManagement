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

    print(new_market_dict["editors"][0])
    new_market = Market(new_market_dict)

    if str(current_user.email) not in list(new_market.editors):
        print(current_user.email, new_market.editors[0])
        return jsonify({"msg": f"Unauthorized user: {current_user.email}"}), 401

    markets = load_markets()
    if new_market.name in markets:
        save_market(new_market)
        return jsonify({"msg": "Market successfully saved"}), 200
    else:
        save_market(new_market)
        return jsonify({"msg": "Market successfully saved"}), 201

# def assign():

