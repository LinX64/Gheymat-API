from flask import Flask

app = Flask(__name__)

@app.route('/get_currencies')
def get_currencies():
    return "Hello, World!"
