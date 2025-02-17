from datetime import datetime
from app import db,login_manager,app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(20), nullable=False)  # 'admin', 'teacher' or 'student'
    phone_number = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_admin = db.Column(db.Boolean, default=False)
    def __init__(self, username, email, role, phone_number, is_admin=False):
        self.username = username
        self.email = email
        self.role = role
        self.phone_number = phone_number
        self.is_admin = is_admin

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return str(self.id)

class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    due_date = db.Column(db.DateTime, nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    file_path = db.Column(db.String(255)) # Add the file path column
    is_checked = db.Column(db.Boolean, default=False) # For plagiarism check status

    # Define the constructor
    def __init__(self, title, description, due_date, teacher_id, file_path):
        self.title = title
        self.description = description
        self.due_date = due_date
        self.teacher_id = teacher_id
        self.file_path = file_path

class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    content_text = db.Column(db.Text, nullable=True)

    assignment = db.relationship('Assignment', backref='submissions')
    student = db.relationship('User', backref='submissions')

    def __init__(self, assignment_id, student_id, file_path, content_text):
        self.assignment_id = assignment_id
        self.student_id = student_id
        self.file_path = file_path
        self.content_text = content_text

class PlagiarismResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment.id'), nullable=False)
    student1_id = db.Column(db.Integer, db.ForeignKey('submission.student_id'), nullable=False)
    student2_id = db.Column(db.Integer, db.ForeignKey('submission.student_id'), nullable=False)
    similarity_score = db.Column(db.Float, nullable=False)
    matched_content = db.Column(db.String(255), nullable=True)

    # Constructor to accept the arguments
    def __init__(self, assignment_id, student1_id, student2_id, similarity_score, matched_content):
        self.assignment_id = assignment_id
        self.student1_id = student1_id
        self.student2_id = student2_id
        self.similarity_score = similarity_score
        self.matched_content = matched_content