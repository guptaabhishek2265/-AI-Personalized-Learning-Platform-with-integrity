import os
from datetime import datetime, timedelta
from flask import render_template, redirect, url_for, flash, request, jsonify, send_file
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from app import app, db
from models import User, Assignment, Submission, PlagiarismResult
from plagiarism_checker import check_plagiarism, extract_text_from_file
import logging
from services.notification import (
    notify_new_assignment,
    notify_assignment_submission,
    notify_plagiarism_check_complete,
    send_sms_notification
)

ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('dashboard_admin'))
        if current_user.role == 'teacher':
            return redirect(url_for('dashboard_teacher'))
        return redirect(url_for('dashboard_student'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        if not email or not password:
            flash('Please provide both email and password', 'error')
            return render_template('login.html')

        app.logger.debug(f"Login attempt for email: {email}")
        user = User.query.filter_by(email=email).first()

        if user:
            app.logger.debug(f"User found with email: {email}")
            if user.check_password(password):
                login_user(user)
                app.logger.debug(f"Login successful for user: {user.username}")
                flash('Logged in successfully!', 'success')
                return redirect(url_for('index'))
            else:
                app.logger.debug("Password check failed")
                flash('Invalid password', 'error')
        else:
            app.logger.debug("User not found")
            flash('Email not registered', 'error')

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')
        phone_number = request.form.get('phone_number')

        app.logger.debug(f"Registration attempt - Username: {username}, Email: {email}, Role: {role}")

        if not all([username, email, password, role, phone_number]):
            flash('Please fill in all fields', 'error')
            return render_template('register.html')

        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return render_template('register.html')

        user = User(
            username=username,
            email=email,
            role=role,
            phone_number=phone_number
        )
        user.set_password(password)

        try:
            db.session.add(user)
            db.session.commit()
            app.logger.debug(f"User registered successfully: {username}")
            flash('Registration successful!', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Registration error: {str(e)}")
            flash('An error occurred during registration', 'error')
            return render_template('register.html')

    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/assignment/<int:assignment_id>/update-due-date', methods=['POST'])
@login_required
def update_due_date(assignment_id):
    if current_user.role != 'teacher':
        return redirect(url_for('index'))
        
    assignment = Assignment.query.get_or_404(assignment_id)
    new_due_date = datetime.strptime(request.form['new_due_date'], '%Y-%m-%dT%H:%M')
    assignment.due_date = new_due_date
    db.session.commit()
    
    # Notify students about due date change
    students = User.query.filter_by(role='student').all()
    message = f"Due date for assignment '{assignment.title}' has been updated to {new_due_date.strftime('%Y-%m-%d %H:%M')}"
    for student in students:
        send_sms_notification(student.id, message)
        
    flash('Due date updated successfully!', 'success')
    return redirect(url_for('dashboard_teacher'))

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
    return render_template('dashboard_student.html', 
                         assignments=assignments, 
                         submissions=submissions,
                         now=datetime.utcnow())

@app.route('/assignment/create', methods=['GET', 'POST'])
@login_required
def create_assignment():
    if current_user.role != 'teacher':
        return redirect(url_for('index'))

    if request.method == 'POST':
        file_path = None
        if 'file' in request.files:
            file = request.files['file']
            if file and file.filename and allowed_file(file.filename):
                try:
                    filename = secure_filename(f"assignment_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename}")
                    if not os.path.exists(app.config['UPLOAD_FOLDER']):
                        os.makedirs(app.config['UPLOAD_FOLDER'])

                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    file_path = filename
                    logging.debug(f"File saved successfully at: {filepath}")
                except Exception as e:
                    logging.error(f"Error saving file: {str(e)}")
                    flash('Error uploading file', 'error')
                    return render_template('create_assignment.html')

        assignment = Assignment(
            title=request.form['title'],
            description=request.form['description'],
            due_date=datetime.strptime(request.form['due_date'], '%Y-%m-%dT%H:%M'),
            teacher_id=current_user.id,
            file_path=file_path
        )
        db.session.add(assignment)
        db.session.commit()

        # Send notifications to all students
        notify_new_assignment(assignment)

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

        # Send notification to teacher about the submission
        notify_assignment_submission(submission)

        # Check if all students have submitted
        submission_count = Submission.query.filter_by(assignment_id=assignment_id).count()
        if submission_count == 60 or datetime.utcnow() > assignment.due_date:
            check_plagiarism(assignment_id)
            # Notify teacher that plagiarism check is complete
            notify_plagiarism_check_complete(assignment)

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
    
    # Check if past due date and not checked yet
    if datetime.utcnow() > assignment.due_date and not assignment.is_checked:
        check_plagiarism(assignment_id)
        
    results = PlagiarismResult.query.filter_by(assignment_id=assignment_id).all()

    # Get student information for the report
    students = User.query.filter_by(role='student').all()
    student_dict = {student.id: student.username for student in students}

    return render_template('view_report.html', 
                         assignment=assignment, 
                         results=results, 
                         students=student_dict)

@app.route('/assignment/<int:assignment_id>/download')
@login_required
def download_assignment_file(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    if not assignment.file_path:
        flash('No file available for this assignment', 'error')
        return redirect(url_for('dashboard_student'))

    try:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], assignment.file_path)
        if not os.path.exists(file_path):
            logging.error(f"File not found at path: {file_path}")
            flash('File not found', 'error')
            return redirect(url_for('dashboard_student'))

        return send_file(
            file_path,
            as_attachment=True,
            download_name=os.path.basename(assignment.file_path)
        )
    except Exception as e:
        logging.error(f"Error downloading file: {str(e)}")
        flash('Error downloading file', 'error')
        return redirect(url_for('dashboard_student'))

@app.route('/dashboard/admin')
@login_required
def dashboard_admin():
    if not current_user.is_admin:
        return redirect(url_for('index'))
    users = User.query.all()
    return render_template('dashboard_admin.html', users=users)

@app.route('/admin/add', methods=['POST'])
@login_required
def add_admin():
    if not current_user.is_admin:
        return redirect(url_for('index'))

    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    phone_number = request.form.get('phone_number')

    if User.query.filter_by(email=email).first():
        flash('Email already registered', 'error')
        return redirect(url_for('dashboard_admin'))

    user = User(
        username=username,
        email=email,
        role='admin',
        phone_number=phone_number,
        is_admin=True
    )
    user.set_password(password)

    try:
        db.session.add(user)
        db.session.commit()
        flash('Administrator added successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error adding admin: {str(e)}")
        flash('Error adding administrator', 'error')

    return redirect(url_for('dashboard_admin'))

@app.route('/user/<int:user_id>/delete', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        return redirect(url_for('index'))

    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('Cannot delete your own account', 'error')
        return redirect(url_for('dashboard_admin'))

    try:
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting user: {str(e)}")
        flash('Error deleting user', 'error')

    return redirect(url_for('dashboard_admin'))

@app.route('/account/delete', methods=['POST'])
@login_required
def delete_account():
    if current_user.is_admin:
        flash('Admin accounts cannot be deleted through this method', 'error')
        return redirect(url_for('dashboard_admin'))

    try:
        db.session.delete(current_user)
        db.session.commit()
        logout_user()
        flash('Your account has been deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting account: {str(e)}")
        flash('Error deleting account', 'error')

    return redirect(url_for('index'))

@app.route('/setup-admin', methods=['GET'])
def setup_admin():
    # Check if admin already exists
    admin = User.query.filter_by(email='sahilkumar12484@gmail.com').first()

    if admin:
        # Update existing user to be admin if not already
        if not admin.is_admin:
            admin.is_admin = True
            admin.role = 'admin'
            admin.username = 'sahil_457'
            admin.phone_number = '+916205929482'
            admin.set_password('451457sa')

            try:
                db.session.commit()
                flash('Existing user updated to admin successfully!', 'success')
            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Error updating admin account: {str(e)}")
                flash('Error updating to admin account', 'error')
    else:
        # Create new admin user
        admin = User(
            username='sahil_457',
            email='sahilkumar12484@gmail.com',
            role='admin',
            phone_number='+916205929482',
            is_admin=True
        )
        admin.set_password('451457sa')

        try:
            db.session.add(admin)
            db.session.commit()
            flash('Admin account created successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error creating admin account: {str(e)}")
            flash('Error creating admin account', 'error')

    return redirect(url_for('login'))