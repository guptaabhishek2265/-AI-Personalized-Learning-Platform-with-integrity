import os
from datetime import datetime,date, timedelta
from mimetypes import guess_type
from pytz import timezone  # Import pytz for timezone support
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, send_file, current_app, abort
from flask_login import login_user, logout_user, login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename,safe_join
from extensions import db, limiter, tokenizer, model, chat_history_ids, login_manager
from models import User, Assignment, Submission, PlagiarismResult, Subject, ClassRecord, Challenge, ChallengeDay
from plagiarism import check_plagiarism
import logging
from services.notification import (
    notify_new_assignment,
    notify_assignment_submission,
    notify_plagiarism_check_complete,
    send_sms_notification,
    notify_registration
)
from transformers import AutoModelForCausalLM, AutoTokenizer
from huggingface_hub import login
import torch
import requests
import re

# Create blueprint
main = Blueprint('main', __name__)

# Add user_loader here
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Define IST timezone
IST = timezone('Asia/Kolkata')

ALLOWED_EXTENSIONS = {
    'pptx', 'ppt', 'xls', 'xlsx', 'doc', 'docx', 'pdf', 'txt', 'zip', 
    'jpg', 'jpeg', 'png', 'gif', 'mp4', 'mov', 'avi', 'mkv', 'mp3', 'wav',
    'json', 'xml', 'html', 'css', 'js', 'java', 'cpp', 'py', 'php',
    'ipynb', 'csv'
}
STUDENT_EXTENSIONS = {'doc', 'docx', 'pdf', 'txt', 'ipynb','jpeg','jpg','png'}

def allowed_file(filename, is_teacher=False):
    if not filename:
        return False
    filename = secure_filename(filename)
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    if is_teacher:
        return ext in ALLOWED_EXTENSIONS
    return ext in STUDENT_EXTENSIONS

@main.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('main.dashboard_admin'))
        elif current_user.role == 'teacher':
            return redirect(url_for('main.dashboard_teacher'))
        elif current_user.role == 'student':
            return redirect(url_for('main.dashboard_student'))
        else:
            flash('Unknown role. Please contact support.', 'error')
            return redirect(url_for('main.login'))
    return redirect(url_for('main.login'))

@main.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        if not email or not password:
            flash('Please provide both email and password', 'error')
            return render_template('login.html')

        current_app.logger.debug(f"Login attempt for email: {email}")
        user = User.query.filter_by(email=email).first()

        if user:
            current_app.logger.debug(f"User found with email: {email}")
            if user.check_password(password):
                login_user(user)
                current_app.logger.debug(f"Login successful for user: {user.username}")
                flash('Logged in successfully!', 'success')
                return redirect(url_for('main.index'))
            else:
                current_app.logger.debug("Password check failed")
                flash('Invalid password', 'error')
        else:
            current_app.logger.debug("User not found")
            flash('Email not registered', 'error')

    return render_template('login.html')

@main.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')
        phone_number = request.form.get('phone_number')

        current_app.logger.debug(f"Registration attempt - Username: {username}, Email: {email}, Role: {role}")

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
            current_app.logger.debug(f"User registered successfully: {username}")
            notify_registration(user)
            flash('Registration successful!', 'success')
            return redirect(url_for('main.login'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Registration error: {str(e)}")
            flash('An error occurred during registration', 'error')
            return render_template('register.html')

    return render_template('register.html')

@main.route('/test-sms')
def test_sms():
    send_sms_notification(1, "Test SMS from PlagiarismDetector")
    return "SMS sent (check logs)"

@main.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('main.index'))

@main.route('/student/add-subject', methods=['GET', 'POST'])
@login_required
def add_subject():
    if current_user.role != 'student':
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        name = request.form.get('name')
        if name:
            subject = Subject(name=name, student_id=current_user.id)
            db.session.add(subject)
            db.session.commit()
            current_app.logger.info(f"Subject {name} added for student {current_user.username}")
            return redirect(url_for('main.view_attendance'))
        else:
            current_app.logger.warning("Subject name not provided")

    return render_template('add_subject.html')

# Route to mark daily attendance
@main.route('/student/mark-attendance', methods=['GET', 'POST'])
@login_required
def mark_attendance():
    if current_user.role != 'student':
        return redirect(url_for('main.index'))

    subjects = Subject.query.filter_by(student_id=current_user.id).all()
    if not subjects:
        return redirect(url_for('main.add_subject'))

    if request.method == 'POST':
        selected_date = request.form.get('date')
        if selected_date:
            selected_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        else:
            selected_date = date.today()

        for subject in subjects:
            class_held = request.form.get(f'class_held_{subject.id}') == 'on'
            attended = request.form.get(f'attended_{subject.id}') == 'on' if class_held else False

            # Check if a record exists for this date and subject
            record = ClassRecord.query.filter_by(subject_id=subject.id, date=selected_date).first()
            if record:
                record.class_held = class_held
                record.attended = attended
            else:
                record = ClassRecord(
                    subject_id=subject.id,
                    date=selected_date,
                    class_held=class_held,
                    attended=attended
                )
                db.session.add(record)
        db.session.commit()
        current_app.logger.info(f"Attendance marked for student {current_user.username} on {selected_date}")
        return redirect(url_for('main.view_attendance'))

    return render_template('mark_attendance.html', subjects=subjects, today=date.today())

# Route to view attendance summary
@main.route('/student/attendance')
@login_required
def view_attendance():
    if current_user.role != 'student':
        return redirect(url_for('main.index'))

    subjects = Subject.query.filter_by(student_id=current_user.id).all()
    attendance_summary = []

    for subject in subjects:
        class_records = ClassRecord.query.filter_by(subject_id=subject.id).all()
        total_classes = sum(1 for record in class_records if record.class_held)
        attended_classes = sum(1 for record in class_records if record.class_held and record.attended)
        percentage = (attended_classes / total_classes * 100) if total_classes > 0 else 0

        attendance_summary.append({
            'subject': subject,
            'total_classes': total_classes,
            'attended_classes': attended_classes,
            'percentage': round(percentage, 2),
            'meets_criterion': percentage >= 75
        })

    return render_template('view_attendance.html', attendance_summary=attendance_summary)

@main.route('/student/remove-subject/<int:subject_id>', methods=['POST'])
@login_required
def remove_subject(subject_id):
    if current_user.role != 'student':
        return redirect(url_for('main.index'))

    subject = Subject.query.get_or_404(subject_id)
    if subject.student_id != current_user.id:
        current_app.logger.warning(f"Unauthorized attempt to delete subject {subject_id} by user {current_user.id}")
        abort(403, description="You can only delete your own subjects")

    # Delete the subject (cascading will remove associated ClassRecords)
    db.session.delete(subject)
    db.session.commit()
    current_app.logger.info(f"Subject {subject.name} (ID: {subject_id}) removed by student {current_user.username}")
    return redirect(url_for('main.view_attendance'))

@main.route('/assignment/<int:assignment_id>/preview')
@login_required
def preview_assignment(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    
    if not assignment.file_path:
        flash('No file available for this assignment', 'error')
        return redirect(url_for('main.dashboard_student'))

    try:
        PREVIEWABLE_TYPES = {'pdf', 'jpg', 'jpeg', 'png', 'txt', 'html', 'json'}
        file_path = safe_join(current_app.config['UPLOAD_FOLDER'], assignment.file_path)
        file_extension = assignment.file_path.rsplit('.', 1)[-1].lower()

        if file_extension not in PREVIEWABLE_TYPES:
            flash('This file type cannot be previewed. Downloading instead.', 'info')
            return send_file(file_path)

        mime_type, _ = guess_type(file_path)
        return send_file(file_path, mimetype=mime_type, as_attachment=False)
    except FileNotFoundError:
        flash('File not found', 'error')
        return redirect(url_for('main.dashboard_student'))
    except Exception as e:
        logging.error(f"Error previewing file: {str(e)}")
        flash('Error previewing file', 'error')
        return redirect(url_for('main.dashboard_student'))

@main.route('/assignment/<int:assignment_id>/submission/<int:submission_id>/preview')
@login_required
def preview_submission(assignment_id,submission_id):
    submission = Submission.query.filter_by(assignment_id=assignment_id, id=submission_id).first_or_404()
    if not submission.file_path:
        flash('No file available for this submission', 'error')
        return redirect(url_for('main.view_submissions', assignment_id=assignment_id))

    try:
        PREVIEWABLE_TYPES = {'pdf', 'jpg', 'jpeg', 'png', 'txt', 'html', 'json'}
        file_path = safe_join(current_app.config['UPLOAD_FOLDER'], submission.file_path)
        print(f"File Path: {file_path}")
        print(f"File Exists: {os.path.exists(file_path)}")

        if not os.path.exists(file_path):
            flash('File not found', 'error')
            return redirect(url_for('main.view_submissions', assignment_id=assignment_id))

        file_extension = submission.file_path.rsplit('.', 1)[-1].lower()

        if file_extension not in PREVIEWABLE_TYPES:
            flash('This file type cannot be previewed. Downloading instead.', 'info')
            return send_file(file_path, as_attachment=True)

        mime_type, _ = guess_type(file_path)
        return send_file(file_path, mimetype=mime_type, as_attachment=False)

    except (FileNotFoundError, OSError):
        flash('File not found', 'error')
        return redirect(url_for('main.view_submissions', assignment_id=assignment_id))
    except Exception as e:
        logging.error(f"Error previewing submission file: {str(e)}")
        flash('Error previewing file', 'error')
        return redirect(url_for('main.view_submissions', assignment_id=assignment_id))

@main.route('/assignment/<int:assignment_id>/update-due-date', methods=['POST'])
@login_required
def update_due_date(assignment_id):
    if current_user.role != 'teacher':
        return jsonify({'error': 'Unauthorized'}), 403
        
    try:
        assignment = Assignment.query.get_or_404(assignment_id)
        new_due_date_str = request.form.get('new_due_date')
        if not new_due_date_str:
            return jsonify({'error': 'No due date provided'}), 400
        # Parse the due date and localize to IST
        new_due_date = IST.localize(datetime.strptime(new_due_date_str, '%Y-%m-%dT%H:%M'))
        assignment.due_date = new_due_date
        db.session.commit()
        
        # Notify students
        students = User.query.filter_by(role='student').all()
        message = f"Due date for assignment '{assignment.title}' has been updated to {new_due_date.strftime('%Y-%m-%d %H:%M')} IST"
        for student in students:
            send_sms_notification(student.id, message)
            
        return jsonify({'success': True, 'message': 'Due date updated successfully'})
    except ValueError as ve:
        logging.error(f"Invalid date format: {str(ve)}")
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DDTHH:MM'}), 400
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error updating due date: {str(e)}")
        return jsonify({'error': str(e)}), 500
    
@main.route('/dashboard/teacher')
@login_required
def dashboard_teacher():
    if current_user.role != 'teacher':
        return redirect(url_for('main.index'))
    assignments = Assignment.query.filter_by(teacher_id=current_user.id).all()
    sorted_assignments = sorted(assignments, key=lambda x: x.due_date)
    submissions_by_assignment = {
        assignment.id: Submission.query.filter_by(assignment_id=assignment.id).all()
        for assignment in assignments
    }

    return render_template(
        'dashboard_teacher.html',
        assignments=sorted_assignments,
        submissions_by_assignment=submissions_by_assignment
    )
    # return render_template('dashboard_teacher.html', assignments=assignments)
@main.route('/assignment/<int:assignment_id>/submissions')
@login_required
def view_submissions(assignment_id):
    if current_user.role != 'teacher':
        return redirect(url_for('main.index'))

    assignment = Assignment.query.get_or_404(assignment_id)
    submissions = Submission.query.filter_by(assignment_id=assignment_id).all()
    for submission in submissions:
        submission.is_late = submission.timestamp > assignment.due_date
    return render_template('view_submissions.html', assignment=assignment, submissions=submissions)

@main.route('/dashboard/student')
@login_required
def dashboard_student():
    if current_user.role != 'student':
        return redirect(url_for('main.index'))
    assignments = Assignment.query.all()
    submissions = {s.assignment_id: s for s in Submission.query.filter_by(student_id=current_user.id).all()}
    sorted_assignments = sorted(assignments, key=lambda x: x.due_date)
    return render_template('dashboard_student.html', 
                         assignments=sorted_assignments, 
                         submissions=submissions,
                         now=datetime.now(IST))  # Use IST for current time

@main.route('/assignment/create', methods=['GET', 'POST'])
@login_required
def create_assignment():
    if current_user.role != 'teacher':
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        file_path = None
        if 'file' in request.files:
            file = request.files['file']
            if file and file.filename and allowed_file(file.filename, is_teacher=True):
                try:
                    filename = secure_filename(f"assignment_{datetime.now(IST).strftime('%Y%m%d%H%M%S')}_{file.filename}")
                    upload_dir = os.path.abspath(current_app.config['UPLOAD_FOLDER'])
                    if not os.path.exists(upload_dir):
                        os.makedirs(upload_dir)

                    filepath = os.path.join(upload_dir, filename)
                    file.save(filepath)
                    file_path = filename
                    logging.debug(f"File saved successfully at: {filepath}")
                except Exception as e:
                    logging.error(f"Error saving file: {str(e)}")
                    flash('Error uploading file', 'error')
                    return render_template('create_assignment.html')

        # Parse due date and localize to IST
        due_date = IST.localize(datetime.strptime(request.form['due_date'], '%Y-%m-%dT%H:%M'))
        assignment = Assignment(
            title=request.form['title'],
            description=request.form['description'],
            due_date=due_date,
            teacher_id=current_user.id,
            file_path=file_path
        )
        db.session.add(assignment)
        db.session.commit()

        # Send notifications to all students
        notify_new_assignment(assignment)

        flash('Assignment created successfully!', 'success')
        return redirect(url_for('main.dashboard_teacher'))

    return render_template('create_assignment.html')

@main.route('/assignment/<int:assignment_id>/delete', methods=['POST'])
@login_required
def delete_assignment(assignment_id):
    if current_user.role != 'teacher':
        flash('Unauthorized access', 'error')
        return redirect(url_for('main.index'))
    
    assignment = Assignment.query.get_or_404(assignment_id)
    if assignment.teacher_id != current_user.id:
        flash('You can only delete your own assignments', 'error')
        return redirect(url_for('main.dashboard_teacher'))
    
    # Delete related submissions and their files
    submissions = Submission.query.filter_by(assignment_id=assignment.id).all()
    for submission in submissions:
        if submission.file_path:
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], submission.file_path)
            if os.path.exists(file_path):
                os.remove(file_path)
        db.session.delete(submission)
    
    # Delete related plagiarism results and their files
    plagiarism_results = PlagiarismResult.query.filter_by(assignment_id=assignment.id).all()
    for result in plagiarism_results:
        if result.report_path and os.path.exists(os.path.join(current_app.config['UPLOAD_FOLDER'], result.report_path)):
            os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], result.report_path))
        if result.graph_path and os.path.exists(os.path.join(current_app.config['UPLOAD_FOLDER'], result.graph_path)):
            os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], result.graph_path))
        db.session.delete(result)
    
    # Delete the assignment file if it exists
    if assignment.file_path:
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], assignment.file_path)
        if os.path.exists(file_path):
            os.remove(file_path)
    
    # Delete the assignment
    db.session.delete(assignment)
    db.session.commit()
    
    flash('Assignment deleted successfully', 'success')
    return redirect(url_for('main.dashboard_teacher'))

@main.route('/assignment/<int:assignment_id>/submit', methods=['POST'])
@login_required
def submit_assignment(assignment_id):
    if current_user.role != 'student':
        return redirect(url_for('main.index'))
        
    assignment = Assignment.query.get_or_404(assignment_id)
    if datetime.now(IST) > assignment.due_date:
        flash('Submission deadline has passed!', 'error')
        return redirect(url_for('main.dashboard_student'))

    if 'file' not in request.files:
        flash('No file uploaded', 'error')
        return redirect(url_for('main.dashboard_student'))

    file = request.files['file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('main.dashboard_student'))

    if file and allowed_file(file.filename, is_teacher=False):
        filename = secure_filename(f"{assignment_id}_{current_user.id}_{file.filename}")
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        file_path = filename
        # Extract text content for plagiarism checking

        submission = Submission(
            assignment_id=assignment_id,
            student_id=current_user.id,
            file_path=file_path,
            content_text=None
        )
        db.session.add(submission)
        db.session.commit()

        # Send notification to teacher about the submission
        notify_assignment_submission(submission)

        flash('Assignment submitted successfully!', 'success')
        return redirect(url_for('main.dashboard_student'))

    flash('Invalid file type', 'error')
    return redirect(url_for('main.dashboard_student'))

@main.route('/assignment/<int:assignment_id>/download-report')
@login_required
def download_report(assignment_id):
    try:
        result = PlagiarismResult.query.filter_by(assignment_id=assignment_id).first_or_404()
        file_path = result.report_path  # Full path

        if not os.path.exists(file_path):
            flash('Report file not found', 'error')
            return redirect(url_for('main.view_report', assignment_id=assignment_id))

        mime_type, _ = guess_type(file_path)
        return send_file(file_path, mimetype=mime_type)

    except Exception as e:
        current_app.logger.error(f"Error viewing report for assignment {assignment_id}: {e}")
        flash('Could not display the report.', 'error')
        return redirect(url_for('main.view_report', assignment_id=assignment_id))

@main.route('/assignment/<int:assignment_id>/download-graph')
@login_required
def download_graph(assignment_id):
    try:
        result = PlagiarismResult.query.filter_by(assignment_id=assignment_id).first_or_404()
        file_path = result.graph_path  # Full path

        if not os.path.exists(file_path):
            flash('Graph file not found', 'error')
            return redirect(url_for('main.view_report', assignment_id=assignment_id))

        mime_type, _ = guess_type(file_path)
        return send_file(file_path, mimetype=mime_type)

    except Exception as e:
        current_app.logger.error(f"Error viewing graph for assignment {assignment_id}: {e}")
        flash('Could not display the graph.', 'error')
        return redirect(url_for('main.view_report', assignment_id=assignment_id))


@main.route('/assignment/<int:assignment_id>/report')
@login_required
def view_report(assignment_id):
    if current_user.role != 'teacher':
        return redirect(url_for('main.index'))

    assignment = Assignment.query.get_or_404(assignment_id)
    now_ist = datetime.now(IST)
    
    # Bypass due date for testing (remove after testing)
    if (now_ist > assignment.due_date) & (assignment.is_checked == False):
        check_plagiarism(assignment_id)
        assignment.is_checked = True
        db.session.commit()
    
    # Query results and convert to serializable format
    results = PlagiarismResult.query.filter_by(assignment_id=assignment_id).all()
    serializable_results = [
        {
            'student1_id': result.student1_id,
            'student2_id': result.student2_id,
            'similarity_score': float(result.similarity_score)  # Ensure it's a float for JSON
        } for result in results
    ] if results else []

    students = User.query.filter_by(role='student').all()
    student_dict = {student.id: student.username for student in students}

    return render_template('view_report.html', 
                          assignment=assignment, 
                          results=serializable_results,  # Pass serialized data
                          students=student_dict)

@main.route('/assignment/<int:assignment_id>/download')
@login_required
def download_assignment_file(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    if not assignment.file_path:
        flash('No file available for this assignment', 'error')
        return redirect(url_for('main.dashboard_student'))

    try:
        if not assignment.file_path:
            flash('No file available for this assignment', 'error')
            return redirect(url_for('main.dashboard_student'))
            
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], assignment.file_path)
        abs_file_path = os.path.abspath(file_path)
        logging.info(f"Looking for file at path: {abs_file_path}")
        if not os.path.exists(abs_file_path):
            # Try to find the file by name only
            file_name = os.path.basename(assignment.file_path)
            alt_path = os.path.join(current_app.config['UPLOAD_FOLDER'], file_name)
            abs_alt_path = os.path.abspath(alt_path)
            if os.path.exists(abs_alt_path):
                file_path = alt_path
            else:
                logging.error(f"File not found at path: {abs_file_path} or {abs_alt_path}")
                flash('File not found', 'error')
            return redirect(url_for('main.dashboard_student'))

        return send_file(
            file_path,
            as_attachment=True,
            download_name=os.path.basename(assignment.file_path)
        )
    except Exception as e:
        logging.error(f"Error downloading file: {str(e)}")
        flash('Error downloading file', 'error')
        return redirect(url_for('main.dashboard_student'))

@main.route('/dashboard/admin')
@login_required
def dashboard_admin():
    if not current_user.is_admin:
        return redirect(url_for('main.index'))
    users = User.query.all()
    return render_template('dashboard_admin.html', users=users)

@main.route('/admin/add', methods=['POST'])
@login_required
def add_admin():
    if not current_user.is_admin:
        return redirect(url_for('main.index'))

    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    phone_number = request.form.get('phone_number')

    if User.query.filter_by(email=email).first():
        flash('Email already registered', 'error')
        return redirect(url_for('main.dashboard_admin'))

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
        current_app.logger.error(f"Error adding admin: {str(e)}")
        flash('Error adding administrator', 'error')

    return redirect(url_for('main.dashboard_admin'))

@main.route('/user/<int:user_id>/delete', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        return redirect(url_for('main.index'))

    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('Cannot delete your own account', 'error')
        return redirect(url_for('main.dashboard_admin'))
    
    if user.is_admin or user.role == 'admin':
        flash('Administrators cannot delete other administrators', 'error')
        return redirect(url_for('main.dashboard_admin'))

    try:
        # Delete all plagiarism results related to the user
        db.session.query(PlagiarismResult).filter(
            (getattr(PlagiarismResult, "student1_id") == user.id) |
            (getattr(PlagiarismResult, "student2_id") == user.id)
        ).delete(synchronize_session=False)
        
        # Delete all submissions by the user if they're a student
        if user.role == 'student':
            Submission.query.filter_by(student_id=user.id).delete()
        
        # Delete all assignments if they're a teacher
        if user.role == 'teacher':
            Assignment.query.filter_by(teacher_id=user.id).delete()
            
        # Delete the user
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting user: {str(e)}")
        flash('Error deleting user', 'error')

    return redirect(url_for('main.dashboard_admin'))

@main.route('/account/delete', methods=['POST'])
@login_required
def delete_account():
    if current_user.is_admin:
        flash('Admin accounts cannot be deleted through this method', 'error')
        return redirect(url_for('main.dashboard_admin'))

    try:
        db.session.delete(current_user)
        db.session.commit()
        logout_user()
        flash('Your account has been deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting account: {str(e)}")
        flash('Error deleting account', 'error')

    return redirect(url_for('main.index'))

@main.route('/setup-admin', methods=['GET'])
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
                current_app.logger.error(f"Error updating admin account: {str(e)}")
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
            current_app.logger.error(f"Error creating admin account: {str(e)}")
            flash('Error creating admin account', 'error')

    return redirect(url_for('main.login'))

@main.route('/student/chatbot', methods=['GET', 'POST'])
@login_required
def student_chatbot():
    if current_user.role != 'student':
        return redirect(url_for('main.index'))
    
    # OpenRouter API configuration
    OPENROUTER_API_KEY = "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"
    OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
    
    if request.method == "POST":
        user_input = request.form.get("user_input", "").strip()
        if not user_input:
            return jsonify({"error": "No input provided"}), 400
            
        # Handle attendance-related queries
        if any(word in user_input.lower() for word in ['attendance', 'present', 'absent', 'rate', 'percentage', 'maintain', 'need']):
            try:
                subjects = Subject.query.filter_by(student_id=current_user.id).all()
                if not subjects:
                    return jsonify({"response": "You haven't added any subjects yet. Please add subjects first to track your attendance."})
                
                attendance_summary = []
                for subject in subjects:
                    class_records = ClassRecord.query.filter_by(subject_id=subject.id).all()
                    total_classes = sum(1 for record in class_records if record.class_held)
                    attended_classes = sum(1 for record in class_records if record.class_held and record.attended)
                    percentage = (attended_classes / total_classes * 100) if total_classes > 0 else 0
                    
                    # Calculate classes needed to reach 75%
                    if total_classes > 0:
                        classes_needed = 0
                        current_percentage = percentage
                        while current_percentage < 75 and classes_needed < 100:  # Limit to prevent infinite loop
                            classes_needed += 1
                            current_percentage = ((attended_classes + classes_needed) / (total_classes + classes_needed)) * 100
                    else:
                        classes_needed = None
                    
                    attendance_summary.append({
                        'subject': subject.name,
                        'percentage': round(percentage, 2),
                        'total_classes': total_classes,
                        'attended_classes': attended_classes,
                        'classes_needed': classes_needed
                    })
                
                if not attendance_summary:
                    return jsonify({"response": "No attendance records found. Please mark your attendance first."})
                
                # Format the response
                response = "Here's your attendance summary and guidance:\n\n"
                for summary in attendance_summary:
                    response += f"{summary['subject']}:\n"
                    response += f"- Current Attendance Rate: {summary['percentage']}%\n"
                    response += f"- Classes Attended: {summary['attended_classes']} out of {summary['total_classes']}\n"
                    response += f"- Status: {'Meets 75% criterion' if summary['percentage'] >= 75 else 'Below 75% criterion'}\n"
                    
                    if summary['percentage'] < 75 and summary['classes_needed'] is not None:
                        if summary['classes_needed'] == 0:
                            response += "- You need to attend all future classes to maintain 75% attendance.\n"
                        else:
                            response += f"- You need to attend {summary['classes_needed']} more class(es) to reach 75% attendance.\n"
                    elif summary['percentage'] >= 75:
                        response += "- You're currently meeting the attendance requirement. Keep attending classes to maintain this rate.\n"
                    response += "\n"
                
                response += "Guidelines to maintain attendance:\n"
                response += "1. Mark your attendance daily using the 'Mark Attendance' button\n"
                response += "2. Attend all scheduled classes\n"
                response += "3. If you miss a class, make sure to attend future classes to maintain the 75% requirement\n"
                response += "4. Check your attendance regularly to stay on track\n"
                response += "5. If you're falling behind, prioritize attending upcoming classes\n\n"
                response += "You can mark your attendance by clicking the 'Mark Attendance' button in your dashboard."
                return jsonify({"response": response})
                
            except Exception as e:
                current_app.logger.error(f"Error processing attendance query: {str(e)}")
                return jsonify({"error": "An error occurred while fetching attendance data"}), 500
        
        # Handle other queries using OpenRouter API
        try:
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "HTTP-Referer": "http://localhost:5000",
                "X-Title": "Student Assistant Chatbot",
                "Content-Type": "application/json"
            }
            
            # Prepare the conversation context
            messages = [
                {
                    "role": "system",
                    "content": """You are a helpful student assistant chatbot. Your role is to provide clear, accurate, and helpful responses to student queries. 
                    You can help with:
                    1. Answering general academic questions
                    2. Providing study guidance
                    3. Helping with course-related queries
                    4. Checking attendance status
                    Always be polite and professional."""
                },
                {"role": "user", "content": user_input}
            ]
            
            data = {
                "model": "openai/gpt-3.5-turbo",
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 500,
                "top_p": 0.9,
                "frequency_penalty": 0.6,
                "presence_penalty": 0.6
            }
            
            current_app.logger.info(f"Sending request to OpenRouter API for input: {user_input}")
            response = requests.post(OPENROUTER_API_URL, headers=headers, json=data, timeout=30)
            
            # Log the response status and headers for debugging
            current_app.logger.info(f"OpenRouter API response status: {response.status_code}")
            current_app.logger.debug(f"OpenRouter API response headers: {response.headers}")
            
            response.raise_for_status()
            response_json = response.json()
            
            # Log the response content for debugging
            current_app.logger.debug(f"OpenRouter API response: {response_json}")
            
            if "choices" not in response_json or not response_json["choices"]:
                raise ValueError("Invalid response format from OpenRouter API")
            
            # Extract the response text
            bot_response = response_json["choices"][0]["message"]["content"]
            
            if not bot_response or bot_response.isspace():
                bot_response = "I'm not sure how to respond to that. Could you please rephrase your question?"
            
            current_app.logger.info(f"Successfully generated response for input: {user_input}")
            return jsonify({"response": bot_response})
            
        except requests.exceptions.Timeout:
            current_app.logger.error("OpenRouter API request timed out")
            return jsonify({"error": "The request took too long to process. Please try again."}), 504
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"OpenRouter API request error: {str(e)}")
            return jsonify({"error": "I'm having trouble connecting to my knowledge base. Please try again in a moment."}), 500
        except (KeyError, ValueError) as e:
            current_app.logger.error(f"Error processing OpenRouter API response: {str(e)}")
            return jsonify({"error": "I received an unexpected response. Please try again."}), 500
        except Exception as e:
            current_app.logger.error(f"Unexpected error in chatbot: {str(e)}")
            return jsonify({"error": "An unexpected error occurred. Please try again later."}), 500
    
    return render_template('student_chatbot.html')

@main.route('/student/create-challenge', methods=['POST'])
@login_required
def create_challenge():
    if current_user.role != 'student':
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        data = request.get_json()
        name = data.get('name')
        days = data.get('days')

        if not name or not days:
            return jsonify({'error': 'Name and days are required'}), 400

        days = int(days)
        if days < 1 or days > 30:
            return jsonify({'error': 'Days must be between 1 and 30'}), 400

        # Delete any existing active challenge for this student
        existing_challenge = Challenge.query.filter_by(
            student_id=current_user.id,
            is_active=True
        ).first()
        
        if existing_challenge:
            # Delete associated challenge days
            ChallengeDay.query.filter_by(challenge_id=existing_challenge.id).delete()
            db.session.delete(existing_challenge)
            db.session.flush()

        # Create new challenge
        challenge = Challenge(
            student_id=current_user.id,
            name=name,
            total_days=days
        )
        db.session.add(challenge)
        db.session.flush()  # Get the challenge ID

        # Create challenge days
        for i in range(1, days + 1):
            challenge_day = ChallengeDay(
                challenge_id=challenge.id,
                day_number=i
            )
            db.session.add(challenge_day)

        db.session.commit()
        
        # Return the challenge data
        return jsonify({
            'success': True,
            'challenge_id': challenge.id,
            'redirect_url': url_for('main.challenge_tracker')
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating challenge: {str(e)}")
        return jsonify({'error': 'Failed to create challenge'}), 500

@main.route('/student/mark-challenge-day', methods=['POST'])
@login_required
def mark_challenge_day():
    if current_user.role != 'student':
        return jsonify({"error": "Unauthorized access"}), 403
        
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
            
        challenge_id = data.get('challenge_id')
        day_number = int(data.get('day_number', 0))
        
        if not challenge_id or day_number < 1:
            return jsonify({"error": "Invalid challenge or day number"}), 400
            
        # Verify challenge belongs to student and is active
        challenge = Challenge.query.filter_by(
            id=challenge_id,
            student_id=current_user.id,
            is_active=True
        ).first_or_404()
        
        # Get the day record
        challenge_day = ChallengeDay.query.filter_by(
            challenge_id=challenge_id,
            day_number=day_number
        ).first_or_404()
        
        # Check if the day is already completed
        if challenge_day.is_completed:
            return jsonify({"error": "Day already marked as completed"}), 400
            
        # Mark the day as completed
        challenge_day.mark_completed()
        db.session.commit()
        
        # Calculate new progress
        progress = (challenge.completed_days / challenge.total_days) * 100
        
        return jsonify({
            "success": True,
            "message": "Day marked as completed",
            "challenge": {
                "id": challenge.id,
                "completed_days": challenge.completed_days,
                "total_days": challenge.total_days,
                "progress": progress,
                "remaining_days": challenge.get_remaining_days()
            }
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error marking challenge day: {str(e)}")
        return jsonify({"error": "Failed to mark day as completed"}), 500

@main.route('/student/challenge-tracker')
@login_required
def challenge_tracker():
    if current_user.role != 'student':
        flash('Unauthorized access', 'danger')
        return redirect(url_for('main.dashboard_student'))
        
    # Get the active challenge for the student
    challenge = Challenge.query.filter_by(
        student_id=current_user.id,
        is_active=True
    ).first()
    
    if challenge:
        # Get all days for this challenge
        challenge.days = ChallengeDay.query.filter_by(
            challenge_id=challenge.id
        ).order_by(ChallengeDay.day_number).all()
        
        # Ensure challenge.start_date is timezone-aware
        if challenge.start_date and challenge.start_date.tzinfo is None:
            challenge.start_date = IST.localize(challenge.start_date)
    
    # Get current time in IST
    now = datetime.now(IST)
    
    return render_template('challenge_tracker.html', 
                         challenge=challenge,
                         now=now)

