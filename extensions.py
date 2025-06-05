from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize extensions
db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
limiter = Limiter(
    get_remote_address,
    default_limits=["100 per minute"]
)

# Global variables for chatbot
tokenizer = None
model = None
chat_history_ids = None

def init_chatbot(app):
    """Initialize the chatbot model and tokenizer"""
    global tokenizer, model, chat_history_ids
    try:
        from huggingface_hub import login
        from transformers import AutoModelForCausalLM, AutoTokenizer
        import torch
        
        # Get Hugging Face token from environment variable
        hf_token = os.getenv('HUGGINGFACE_TOKEN')
        if not hf_token:
            app.logger.error("HUGGINGFACE_TOKEN not found in environment variables")
            return
            
        login(token=hf_token)
        tokenizer = AutoTokenizer.from_pretrained("microsoft/DialoGPT-small", use_auth_token=True)
        model = AutoModelForCausalLM.from_pretrained("microsoft/DialoGPT-small", use_auth_token=True)
        chat_history_ids = None
        app.logger.info("Chatbot initialized successfully")
    except Exception as e:
        app.logger.error(f"Error initializing chatbot: {str(e)}")
        tokenizer = None
        model = None
        chat_history_ids = None 