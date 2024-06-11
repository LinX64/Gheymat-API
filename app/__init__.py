from flask import Flask


def create_app():
    app = Flask(__name__)

    # Load the configuration from config.py
    app.config.from_pyfile('config.py')

    # Register Blueprints
    from .routes import main as main_blueprint
    app.register_blueprint(main_blueprint)

    return app
