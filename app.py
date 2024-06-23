from flask import jsonify

from app import create_app
from app.helper import aggregator

myCurrencyApp = create_app()


@myCurrencyApp.route('/get_currencies')
async def get_currencies():
    data = await aggregator()
    return jsonify(data)

if __name__ == '__main__':
    myCurrencyApp.run(debug=False, host='localhost', port=5050)