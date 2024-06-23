from flask import Flask, jsonify
from app.helper import aggregator

app = Flask(__name__)


@app.route('/get_currencies')
def get_currencies():
    data = aggregator()
    return jsonify(data)


app = app
