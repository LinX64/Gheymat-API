from flask import Flask, request, jsonify, Blueprint


main = Blueprint('main', __name__)


@main.route('/')
def index():
    return "Hello, World!"


@main.route('/get_currencies')
def get_currencies():
    
    return 'Test'


@main.route('/timeframe', methods=['POST'])
def handle_post_timeframe():
    data = request.json

    timeframe = data.get('timeframe', '1H')

    response = {
        'message': 'Received POST request!',
        'data': f'Received: {timeframe}'
    }

    return jsonify(response)
