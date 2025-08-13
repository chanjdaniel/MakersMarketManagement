from flask import request, jsonify
from models import db, User, Market, Organization
from sqlalchemy.exc import IntegrityError

def load_market_request(current_user, request):
    data = request.json

    name = data.get("name")

    market = load_market(name)
    if market is None:
        return jsonify({"msg": "Market not found"}), 404

    if current_user.email in market.viewers:
        return jsonify({"msg": "Market successfully loaded", "market": market}), 200
        
    else:
        return jsonify({"msg": "Unauthorized user"}), 401

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
