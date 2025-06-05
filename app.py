import os
import logging
from flask import Flask
from dotenv import load_dotenv
from datetime import timedelta
from extensions import db, login_manager, migrate, limiter, init_chatbot

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.DEBUG)

def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY")

    # Configure database
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_recycle": 300,
        "pool_pre_ping": True,
    }
    app.config["UPLOAD_FOLDER"] = "uploads"
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)

    login_manager.login_view = "login"
    login_manager.login_message_category = "info"

    # Register blueprints and import routes
    with app.app_context():
        from routes import main as main_blueprint
        app.register_blueprint(main_blueprint)
        
        # Initialize chatbot
        init_chatbot(app)

    return app

app = create_app()

if __name__ == '__main__':
    app.run(debug=True)

