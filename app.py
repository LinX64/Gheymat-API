from flask import Flask, jsonify
from app.helper import aggregator


def create_app():
    app = Flask(__name__)

    @app.route('/get_currencies')
    def get_currencies():
        data = aggregator()  # Remove async/await unless you're using a Flask extension that supports it
        return jsonify(data)

    return app


# This line is what Vercel will use
app = create_app()

# Keep this for local testing, Vercel will ignore it
if __name__ == '__main__':
    app.run(debug=True, host='localhost', port=5050)
