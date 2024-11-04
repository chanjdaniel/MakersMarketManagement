from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import json
import os

app = Flask(__name__)
CORS(app)
DATA_FILE = 'data/tables.json'

def read_data():
    """Read JSON data from the file."""
    if not os.path.exists(DATA_FILE):
        return []  # Return an empty list if the file doesn't exist
    with open(DATA_FILE, 'r') as file:
        return json.load(file)

def write_data(data):
    """Write JSON data to the file."""
    with open(DATA_FILE, 'w') as file:
        json.dump(data, file, indent=4)

@app.route('/add', methods=['POST'])
def add_table():
    """Add a new table assignment."""
    new_table = request.json  # Expecting JSON data from the request
    data = read_data()
    data.append(new_table)
    write_data(data)
    return jsonify({"message": "Table added successfully!", "data": data}), 201

@app.route('/tables', methods=['GET'])
def get_tables():
    """Return all table assignments as JSON."""
    data = read_data()
    return jsonify(data)

if __name__ == '__main__':
    app.run(debug=True)