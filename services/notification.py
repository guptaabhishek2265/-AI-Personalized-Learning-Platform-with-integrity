import os
import logging
from flask import url_for
from twilio.rest import Client
from datetime import datetime, timedelta
from pytz import timezone
from models import Assignment, Submission, User,PlagiarismResult
# app.py
from dotenv import load_dotenv
load_dotenv()
# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Define IST timezone
IST = timezone('Asia/Kolkata')
def notify_plagiarism_report(assignment):
    teacher = User.query.get(assignment.teacher_id)
    subject = f"Plagiarism Report for Assignment {assignment.title}"
    result = PlagiarismResult.query.filter_by(assignment_id=assignment.id).first()
    if result:
        message = (f"Dear {teacher.username},\n\n"
                   f"The plagiarism report for assignment '{assignment.title}' is ready.\n"
                   f"Download PDF: {url_for('download_report', assignment_id=assignment.id, _external=True)}\n"
                   f"Download Graph: {url_for('download_graph', assignment_id=assignment.id, _external=True)}\n\n"
                   f"Regards,\nPlagiarismDetector Team")
        # send_email_notification(teacher.id, subject, message)
    else:
        message = f"Dear {teacher.username},\n\nNo significant plagiarism detected for assignment '{assignment.title}'."
        # send_email_notification(teacher.id, subject, message)

def send_sms_notification(user_id, message):
    """Send SMS notification to a user"""
    try:
        # Get Twilio credentials from environment
        account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
        auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
        from_number = os.environ.get('TWILIO_PHONE_NUMBER')
        
        if not all([account_sid, auth_token, from_number]):
            logger.error("Missing Twilio credentials. Ensure TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_PHONE_NUMBER are set.")
            return False
        
        # Get user's phone number
        user = User.query.get(user_id)
        if not user or not user.phone_number:
            logger.error(f"No phone number found for user {user_id}")
            return False
        
        # Ensure phone number is in E.164 format (e.g., +91xxxxxxxxxx)
        to_number = user.phone_number if user.phone_number.startswith('+') else f"+{user.phone_number}"
        
        # Initialize Twilio client
        client = Client(account_sid, auth_token)
        
        # Send message
        client.messages.create(
            body=message,
            from_=from_number,
            to=to_number
        )
        logger.info(f"SMS notification sent to user {user_id} at {to_number}")
        return True
        
    except Exception as e:
        logger.error(f"Error sending SMS notification to user {user_id}: {str(e)}")
        return False

def notify_new_assignment(assignment):
    """Notify all students when a new assignment is created"""
    students = User.query.filter_by(role='student').all()
    # Use IST for due_date display
    message = f"New Assignment: {assignment.title}\nDue Date: {assignment.due_date.astimezone(IST).strftime('%Y-%m-%d %H:%M IST')}"
    
    for student in students:
        send_sms_notification(student.id, message)

def notify_assignment_submission(submission):
    """Notify teacher when a student submits an assignment"""
    assignment = submission.assignment
    student = User.query.get(submission.student_id)
    message = f"Student {student.username} has submitted the assignment: {assignment.title}"
    send_sms_notification(assignment.teacher_id, message)

def notify_plagiarism_check_complete(assignment):
    """Notify teacher when plagiarism check is complete"""
    message = f"Plagiarism check completed for assignment: {assignment.title}"
    send_sms_notification(assignment.teacher_id, message)

def notify_due_date_update(assignment):
    """Notify all students when an assignment's due date is updated"""
    students = User.query.filter_by(role='student').all()
    message = f"Due date updated for assignment '{assignment.title}' to {assignment.due_date.astimezone(IST).strftime('%Y-%m-%d %H:%M IST')}"
    for student in students:
        send_sms_notification(student.id, message)

def notify_registration(user):
    """Notify user when they register"""
    message = f"Welcome {user.username}! You have successfully registered on PlagiarismDetector at {datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}."
    send_sms_notification(user.id, message)

def check_approaching_deadlines():
    """Check for assignments due in 24 hours and notify students"""
    now = datetime.now(IST)  # Use IST instead of UTC
    tomorrow = now + timedelta(days=1)

    # Find assignments due in the next 24 hours in IST
    approaching_assignments = Assignment.query.filter(
        Assignment.due_date > now,
        Assignment.due_date <= tomorrow
    ).all()

    students = User.query.filter_by(role='student').all()

    for assignment in approaching_assignments:
        message = f"REMINDER: Assignment '{assignment.title}' is due in less than 24 hours ({assignment.due_date.astimezone(IST).strftime('%Y-%m-%d %H:%M IST')})"
        for student in students:
            # Check if student hasn't submitted yet
            if not Submission.query.filter_by(assignment_id=assignment.id, student_id=student.id).first():
                send_sms_notification(student.id, message)