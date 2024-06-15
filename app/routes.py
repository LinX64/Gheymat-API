from flask import request, jsonify, Blueprint
from .helper import aggregator


main = Blueprint('main', __name__)


@main.route('/')
def index():
    return "Hello, World!"


@main.route('/get_currencies')
async def get_currencies():
    data = await aggregator()
    return jsonify(data)


@main.route('/timeframe', methods=['POST'])
def handle_post_timeframe():
    data = request.json

    timeframe = data.get('timeframe', '1H')

    response = {
        'message': 'Received POST request!',
        'data': f'Received: {timeframe}'
    }

    return jsonify(response)
