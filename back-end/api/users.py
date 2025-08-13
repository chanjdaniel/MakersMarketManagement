from flask import request, jsonify
from models import db, User, Organization, user_organization
from sqlalchemy.exc import IntegrityError

# curl -k -X POST https://127.0.0.1:5000/register-user \
#      -H "Content-Type: application/json" \
#      -d '{"email": "USERNAME", "password": "pswrdpswrd!!!", "organizations": [], "markets": []}'
def register_user(bcrypt, request):
    data = request.json
    email = data.get("email")
    password = data.get("password")
    organizations = data.get("organizations")
    markets = data.get("markets")

    users = load_users()

    if not email or not password:
        return jsonify({"msg": "Email, password, and organization required"}), 400

    if email in users:
        return jsonify({"msg": "User already exists"}), 400

    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
    users[email] = { "email": email, "password": hashed_password, "organizations": organizations, "markets": markets }
    save_users(users)

    return jsonify({"msg": "User registered successfully"}), 201

def login(bcrypt, login_user, request):
    data = request.json
    email, password = data.get('email'), data.get('password')

    users = load_users()
    user = users.get(email)
    if email in users and bcrypt.check_password_hash(users[email]["password"], password):
        user_email = user["email"]
        user_organizations = user["organizations"]
        user_markets = user["markets"]
        user_obj = User(user)
        login_user(user_obj, remember=True)

        user_data = { "email": user_email, "organizations": user_organizations, "markets": user_markets }
        return jsonify({"message": "Login successful", "user_data": user_data}), 200

    return jsonify({"msg": "Invalid credentials"}), 401

def logout(logout_user):
    logout_user()
    return jsonify({"msg": "Logged out"}), 200

def check_session(current_user):
    return jsonify({"email": current_user.email}), 200
