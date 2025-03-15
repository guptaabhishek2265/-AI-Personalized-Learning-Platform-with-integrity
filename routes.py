import os
from datetime import datetime,date
from mimetypes import guess_type
from pytz import timezone  # Import pytz for timezone support
from flask import render_template, redirect, url_for, flash, request, jsonify, send_file, current_app, abort
from flask_login import login_user, logout_user, login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename,safe_join
from app import db, app
from models import User, Assignment, Submission, PlagiarismResult, Subject, ClassRecord
from plagiarism import check_plagiarism
import logging
from services.notification import (
    notify_new_assignment,
    notify_assignment_submission,
    notify_plagiarism_check_complete,
    send_sms_notification,
    notify_registration
)
limiter = Limiter(
    get_remote_address,  # Correct way to define key_func
    app=app,             # Attach the app here
    default_limits=["5 per minute"]  # Default limit applied globally
)
# Define IST timezone
IST = timezone('Asia/Kolkata')

ALLOWED_EXTENSIONS = {
    'pptx', 'ppt', 'xls', 'xlsx', 'doc', 'docx', 'pdf', 'txt', 'zip', 
    'jpg', 'jpeg', 'png', 'gif', 'mp4', 'mov', 'avi', 'mkv', 'mp3', 'wav',
    'json', 'xml', 'html', 'css', 'js', 'java', 'c', 'cpp', 'py', 'php',
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

@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('dashboard_admin'))
        elif current_user.role == 'teacher':
            return redirect(url_for('dashboard_teacher'))
        elif current_user.role == 'student':
            return redirect(url_for('dashboard_student'))
        else:
            flash('Unknown role. Please contact support.', 'error')
            return redirect(url_for('login'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
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
            notify_registration(user)
            flash('Registration successful!', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Registration error: {str(e)}")
            flash('An error occurred during registration', 'error')
            return render_template('register.html')

    return render_template('register.html')

@app.route('/test-sms')
def test_sms():
    send_sms_notification(1, "Test SMS from PlagiarismDetector")
    return "SMS sent (check logs)"

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('index'))

@app.route('/student/add-subject', methods=['GET', 'POST'])
@login_required
def add_subject():
    if current_user.role != 'student':
        return redirect(url_for('index'))

    if request.method == 'POST':
        name = request.form.get('name')
        if name:
            subject = Subject(name=name, student_id=current_user.id)
            db.session.add(subject)
            db.session.commit()
            current_app.logger.info(f"Subject {name} added for student {current_user.username}")
            return redirect(url_for('view_attendance'))
        else:
            current_app.logger.warning("Subject name not provided")

    return render_template('add_subject.html')

# Route to mark daily attendance
@app.route('/student/mark-attendance', methods=['GET', 'POST'])
@login_required
def mark_attendance():
    if current_user.role != 'student':
        return redirect(url_for('index'))

    subjects = Subject.query.filter_by(student_id=current_user.id).all()
    if not subjects:
        return redirect(url_for('add_subject'))

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
        return redirect(url_for('view_attendance'))

    return render_template('mark_attendance.html', subjects=subjects, today=date.today())

# Route to view attendance summary
@app.route('/student/attendance')
@login_required
def view_attendance():
    if current_user.role != 'student':
        return redirect(url_for('index'))

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

@app.route('/student/remove-subject/<int:subject_id>', methods=['POST'])
@login_required
def remove_subject(subject_id):
    if current_user.role != 'student':
        return redirect(url_for('index'))

    subject = Subject.query.get_or_404(subject_id)
    if subject.student_id != current_user.id:
        current_app.logger.warning(f"Unauthorized attempt to delete subject {subject_id} by user {current_user.id}")
        abort(403, description="You can only delete your own subjects")

    # Delete the subject (cascading will remove associated ClassRecords)
    db.session.delete(subject)
    db.session.commit()
    current_app.logger.info(f"Subject {subject.name} (ID: {subject_id}) removed by student {current_user.username}")
    return redirect(url_for('view_attendance'))

@app.route('/assignment/<int:assignment_id>/preview')
@login_required
def preview_assignment(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    
    if not assignment.file_path:
        flash('No file available for this assignment', 'error')
        return redirect(url_for('dashboard_student'))

    try:
        PREVIEWABLE_TYPES = {'pdf', 'jpg', 'jpeg', 'png', 'txt', 'html', 'json'}
        file_path = safe_join(app.config['UPLOAD_FOLDER'], assignment.file_path)
        file_extension = assignment.file_path.rsplit('.', 1)[-1].lower()

        if file_extension not in PREVIEWABLE_TYPES:
            flash('This file type cannot be previewed. Downloading instead.', 'info')
            return send_file(file_path)

        mime_type, _ = guess_type(file_path)
        return send_file(file_path, mimetype=mime_type, as_attachment=False)
    except FileNotFoundError:
        flash('File not found', 'error')
        return redirect(url_for('dashboard_student'))
    except Exception as e:
        logging.error(f"Error previewing file: {str(e)}")
        flash('Error previewing file', 'error')
        return redirect(url_for('dashboard_student'))

@app.route('/assignment/<int:assignment_id>/submission/<int:submission_id>/preview')
@login_required
def preview_submission(assignment_id,submission_id):
    submission = Submission.query.filter_by(assignment_id=assignment_id, id=submission_id).first_or_404()
    if not submission.file_path:
        flash('No file available for this submission', 'error')
        return redirect(url_for('view_submissions', assignment_id=assignment_id))

    try:
        PREVIEWABLE_TYPES = {'pdf', 'jpg', 'jpeg', 'png', 'txt', 'html', 'json'}
        file_path = safe_join(app.config['UPLOAD_FOLDER'], submission.file_path)
        print(f"File Path: {file_path}")
        print(f"File Exists: {os.path.exists(file_path)}")

        if not os.path.exists(file_path):
            flash('File not found', 'error')
            return redirect(url_for('view_submissions', assignment_id=assignment_id))

        file_extension = submission.file_path.rsplit('.', 1)[-1].lower()

        if file_extension not in PREVIEWABLE_TYPES:
            flash('This file type cannot be previewed. Downloading instead.', 'info')
            return send_file(file_path, as_attachment=True)

        mime_type, _ = guess_type(file_path)
        return send_file(file_path, mimetype=mime_type, as_attachment=False)

    except (FileNotFoundError, OSError):
        flash('File not found', 'error')
        return redirect(url_for('view_submissions', assignment_id=assignment_id))
    except Exception as e:
        logging.error(f"Error previewing submission file: {str(e)}")
        flash('Error previewing file', 'error')
        return redirect(url_for('view_submissions', assignment_id=assignment_id))

@app.route('/assignment/<int:assignment_id>/update-due-date', methods=['POST'])
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
    
@app.route('/dashboard/teacher')
@login_required
def dashboard_teacher():
    if current_user.role != 'teacher':
        return redirect(url_for('index'))
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
@app.route('/assignment/<int:assignment_id>/submissions')
@login_required
def view_submissions(assignment_id):
    if current_user.role != 'teacher':
        return redirect(url_for('index'))

    assignment = Assignment.query.get_or_404(assignment_id)
    submissions = Submission.query.filter_by(assignment_id=assignment_id).all()
    for submission in submissions:
        submission.is_late = submission.timestamp > assignment.due_date
    return render_template('view_submissions.html', assignment=assignment, submissions=submissions)

@app.route('/dashboard/student')
@login_required
def dashboard_student():
    if current_user.role != 'student':
        return redirect(url_for('index'))
    assignments = Assignment.query.all()
    submissions = {s.assignment_id: s for s in Submission.query.filter_by(student_id=current_user.id).all()}
    sorted_assignments = sorted(assignments, key=lambda x: x.due_date)
    return render_template('dashboard_student.html', 
                         assignments=sorted_assignments, 
                         submissions=submissions,
                         now=datetime.now(IST))  # Use IST for current time

@app.route('/assignment/create', methods=['GET', 'POST'])
@login_required
def create_assignment():
    if current_user.role != 'teacher':
        return redirect(url_for('index'))

    if request.method == 'POST':
        file_path = None
        if 'file' in request.files:
            file = request.files['file']
            if file and file.filename and allowed_file(file.filename, is_teacher=True):
                try:
                    filename = secure_filename(f"assignment_{datetime.now(IST).strftime('%Y%m%d%H%M%S')}_{file.filename}")
                    upload_dir = os.path.abspath(app.config['UPLOAD_FOLDER'])
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
        return redirect(url_for('dashboard_teacher'))

    return render_template('create_assignment.html')

@app.route('/assignment/<int:assignment_id>/submit', methods=['POST'])
@login_required
def submit_assignment(assignment_id):
    if current_user.role != 'student':
        return redirect(url_for('index'))
        
    assignment = Assignment.query.get_or_404(assignment_id)
    if datetime.now(IST) > assignment.due_date:
        flash('Submission deadline has passed!', 'error')
        return redirect(url_for('dashboard_student'))

    if 'file' not in request.files:
        flash('No file uploaded', 'error')
        return redirect(url_for('dashboard_student'))

    file = request.files['file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('dashboard_student'))

    if file and allowed_file(file.filename, is_teacher=False):
        filename = secure_filename(f"{assignment_id}_{current_user.id}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
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
        return redirect(url_for('dashboard_student'))

    flash('Invalid file type', 'error')
    return redirect(url_for('dashboard_student'))

@app.route('/assignment/<int:assignment_id>/download-report')
@login_required
def download_report(assignment_id):
    try:
        result = PlagiarismResult.query.filter_by(assignment_id=assignment_id).first_or_404()
        file_path = safe_join(app.config['UPLOAD_FOLDER'], result.report_path)

        if not os.path.exists(file_path):
            flash('Report file not found', 'error')
            return redirect(url_for('view_report', assignment_id=assignment_id))

        mime_type, _ = guess_type(file_path)
        return send_file(file_path, mimetype=mime_type, as_attachment=True)

    except FileNotFoundError:
        flash('The requested report file could not be found.', 'error')
        return redirect(url_for('view_report', assignment_id=assignment_id))
    
    except PermissionError:
        flash('Permission denied: Unable to access the report file.', 'error')
        return redirect(url_for('view_report', assignment_id=assignment_id))

    except Exception as e:
        logging.error(f"Error downloading report for assignment {assignment_id}: {e}")
        flash('An unexpected error occurred while downloading the report.', 'error')
        return redirect(url_for('view_report', assignment_id=assignment_id))


@app.route('/assignment/<int:assignment_id>/download-graph')
@login_required
def download_graph(assignment_id):
    try:
        result = PlagiarismResult.query.filter_by(assignment_id=assignment_id).first_or_404()
        file_path = safe_join(app.config['UPLOAD_FOLDER'], result.graph_path)

        if not os.path.exists(file_path):
            flash('Graph file not found', 'error')
            return redirect(url_for('view_report', assignment_id=assignment_id))

        mime_type, _ = guess_type(file_path)
        return send_file(file_path, mimetype=mime_type, as_attachment=True)

    except FileNotFoundError:
        flash('The requested graph file could not be found.', 'error')
        return redirect(url_for('view_report', assignment_id=assignment_id))
    
    except PermissionError:
        flash('Permission denied: Unable to access the graph file.', 'error')
        return redirect(url_for('view_report', assignment_id=assignment_id))

    except Exception as e:
        logging.error(f"Error downloading graph for assignment {assignment_id}: {e}")
        flash('An unexpected error occurred while downloading the graph.', 'error')
        return redirect(url_for('view_report', assignment_id=assignment_id))

    # return send_file(result.graph_path, as_attachment=True)

@app.route('/assignment/<int:assignment_id>/report')
@login_required
def view_report(assignment_id):
    if current_user.role != 'teacher':
        return redirect(url_for('index'))

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

@app.route('/assignment/<int:assignment_id>/download')
@login_required
def download_assignment_file(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    if not assignment.file_path:
        flash('No file available for this assignment', 'error')
        return redirect(url_for('dashboard_student'))

    try:
        if not assignment.file_path:
            flash('No file available for this assignment', 'error')
            return redirect(url_for('dashboard_student'))
            
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], assignment.file_path)
        abs_file_path = os.path.abspath(file_path)
        logging.info(f"Looking for file at path: {abs_file_path}")
        if not os.path.exists(abs_file_path):
            # Try to find the file by name only
            file_name = os.path.basename(assignment.file_path)
            alt_path = os.path.join(app.config['UPLOAD_FOLDER'], file_name)
            abs_alt_path = os.path.abspath(alt_path)
            if os.path.exists(abs_alt_path):
                file_path = alt_path
            else:
                logging.error(f"File not found at path: {abs_file_path} or {abs_alt_path}")
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
    
    if user.is_admin or user.role == 'admin':
        flash('Administrators cannot delete other administrators', 'error')
        return redirect(url_for('dashboard_admin'))

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