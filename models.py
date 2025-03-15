from datetime import datetime
from pytz import timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager
IST = timezone('Asia/Kolkata')
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    student = db.relationship('User', backref=db.backref('subjects', lazy=True))
class ClassRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    class_held = db.Column(db.Boolean, nullable=False, default=False)  # Was there a class?
    attended = db.Column(db.Boolean, nullable=False, default=False)  # Did the student attend?
    subject = db.relationship('Subject', backref=db.backref('class_records', lazy=True, cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('subject_id', 'date', name='unique_subject_date'),
    )
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(20), nullable=False)  # 'admin', 'teacher' or 'student'
    phone_number = db.Column(db.String(20))
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(IST))
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

class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    due_date = db.Column(db.DateTime(timezone=True), nullable=False)  # Add timezone=True
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    file_path = db.Column(db.String(255))
    is_checked = db.Column(db.Boolean, default=False)

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
    timestamp = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(IST), nullable=False)
    assignment = db.relationship('Assignment', backref='submissions')
    student = db.relationship('User', backref='submissions')

    def __init__(self, assignment_id, student_id, file_path, content_text):
        self.assignment_id = assignment_id
        self.student_id = student_id
        self.file_path = file_path
        self.content_text = content_text
        self.timestamp = datetime.now(IST)

class PlagiarismResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment.id'), nullable=False)
    student1_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    student2_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    similarity_score = db.Column(db.Float, nullable=False)
    matched_content = db.Column(db.String(255), nullable=False)
    report_path = db.Column(db.String(255))
    graph_path = db.Column(db.String(255))

    def __init__(self, assignment_id, student1_id, student2_id, similarity_score, matched_content,report_path,graph_path):
        self.assignment_id = assignment_id
        self.student1_id = student1_id
        self.student2_id = student2_id
        self.similarity_score = similarity_score
        self.matched_content = matched_content
        self.report_path=report_path
        self.graph_path=graph_path
