from os import path
from flask import Flask
from .routes import main as main_blueprint


def create_app():
    app = Flask(__name__, instance_relative_config=True)

    # Load the configuration from config.py
    config_path = path.join(path.dirname(path.abspath(__file__)), '../config.py')
    app.config.from_pyfile(config_path)

    # Register Blueprints
    app.register_blueprint(main_blueprint)

    return app
