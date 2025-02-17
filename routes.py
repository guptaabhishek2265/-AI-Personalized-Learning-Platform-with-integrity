import os
from datetime import datetime
from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from app import app, db
from models import User, Assignment, Submission, PlagiarismResult
from plagiarism_checker import check_plagiarism, extract_text_from_file

ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'teacher':
            return redirect(url_for('dashboard_teacher'))
        return redirect(url_for('dashboard_student'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid email or password', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        user = User(
            username=request.form['username'],
            email=request.form['email'],
            role=request.form['role']
        )
        user.set_password(request.form['password'])
        db.session.add(user)
        db.session.commit()
        flash('Registration successful!', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard/teacher')
@login_required
def dashboard_teacher():
    if current_user.role != 'teacher':
        return redirect(url_for('index'))
    assignments = Assignment.query.filter_by(teacher_id=current_user.id).all()
    return render_template('dashboard_teacher.html', assignments=assignments)

@app.route('/dashboard/student')
@login_required
def dashboard_student():
    if current_user.role != 'student':
        return redirect(url_for('index'))
    assignments = Assignment.query.all()
    submissions = {s.assignment_id: s for s in Submission.query.filter_by(student_id=current_user.id).all()}
    return render_template('dashboard_student.html', assignments=assignments, submissions=submissions)

@app.route('/assignment/create', methods=['GET', 'POST'])
@login_required
def create_assignment():
    if current_user.role != 'teacher':
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        assignment = Assignment(
            title=request.form['title'],
            description=request.form['description'],
            due_date=datetime.strptime(request.form['due_date'], '%Y-%m-%dT%H:%M'),
            teacher_id=current_user.id
        )
        db.session.add(assignment)
        db.session.commit()
        flash('Assignment created successfully!', 'success')
        return redirect(url_for('dashboard_teacher'))
    
    return render_template('create_assignment.html')

@app.route('/assignment/<int:assignment_id>/submit', methods=['POST'])
@login_required
def submit_assignment(assignment_id):
    if current_user.role != 'student':
        return redirect(url_for('index'))
    
    assignment = Assignment.query.get_or_404(assignment_id)
    if datetime.utcnow() > assignment.due_date:
        flash('Submission deadline has passed!', 'error')
        return redirect(url_for('dashboard_student'))
    
    if 'file' not in request.files:
        flash('No file uploaded', 'error')
        return redirect(url_for('dashboard_student'))
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('dashboard_student'))
    
    if file and allowed_file(file.filename):
        filename = secure_filename(f"{assignment_id}_{current_user.id}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Extract text content for plagiarism checking
        content_text = extract_text_from_file(filepath)
        
        submission = Submission(
            assignment_id=assignment_id,
            student_id=current_user.id,
            file_path=filepath,
            content_text=content_text
        )
        db.session.add(submission)
        db.session.commit()
        
        # Check if all students have submitted
        submission_count = Submission.query.filter_by(assignment_id=assignment_id).count()
        if submission_count == 60 or datetime.utcnow() > assignment.due_date:
            check_plagiarism(assignment_id)
        
        flash('Assignment submitted successfully!', 'success')
        return redirect(url_for('dashboard_student'))
    
    flash('Invalid file type', 'error')
    return redirect(url_for('dashboard_student'))

@app.route('/assignment/<int:assignment_id>/report')
@login_required
def view_report(assignment_id):
    if current_user.role != 'teacher':
        return redirect(url_for('index'))
    
    assignment = Assignment.query.get_or_404(assignment_id)
    results = PlagiarismResult.query.filter_by(assignment_id=assignment_id).all()
    
    # Get student information for the report
    students = User.query.filter_by(role='student').all()
    student_dict = {student.id: student.username for student in students}
    
    return render_template('view_report.html', 
                         assignment=assignment, 
                         results=results, 
                         students=student_dict)
