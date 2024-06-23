from flask import Flask, jsonify

app = Flask(__name__)


@app.route('/get_currencies')
def get_currencies():
    currencies = ["USD", "EUR", "JPY", "GBP", "AUD"]
    return jsonify(currencies)
