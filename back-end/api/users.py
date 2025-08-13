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
    organizations = data.get("organizations", [])
    markets = data.get("markets", [])

    if not email or not password:
        return jsonify({"msg": "Email, password required"}), 400

    # Check if user already exists
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({"msg": "User already exists"}), 400

    try:
        # Create new user
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(email=email, password_hash=hashed_password)
        
        db.session.add(new_user)
        db.session.commit()

        return jsonify({"msg": "User registered successfully"}), 201
    
    except IntegrityError:
        db.session.rollback()
        return jsonify({"msg": "User already exists"}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": f"Registration failed: {str(e)}"}), 500

def login(bcrypt, login_user, request):
    data = request.json
    email, password = data.get('email'), data.get('password')

    if not email or not password:
        return jsonify({"msg": "Email and password required"}), 400

    # Find user by email
    user = User.query.filter_by(email=email).first()
    
    if user and bcrypt.check_password_hash(user.password_hash, password):
        login_user(user, remember=True)

        # Prepare user data for response
        user_data = {
            "email": user.email,
            "organizations": [org.to_dict() for org in user.organizations],
            "markets": [market.name for market in user.owned_markets]
        }
        return jsonify({"message": "Login successful", "user_data": user_data}), 200

    return jsonify({"msg": "Invalid credentials"}), 401

def logout(logout_user):
    logout_user()
    return jsonify({"msg": "Logged out"}), 200

def check_session(current_user):
    return jsonify({"email": current_user.email}), 200


