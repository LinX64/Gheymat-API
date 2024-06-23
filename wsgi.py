from flask import jsonify

from app import create_app
from app.helper import aggregator

myApp = create_app()


@myApp.route('/get_currencies')
async def get_currencies():
    data = await aggregator()
    return jsonify(data)

if __name__ == '__main__':
    myApp.run(debug=True, host='localhost', port=5050)