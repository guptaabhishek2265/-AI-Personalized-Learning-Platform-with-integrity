import os
import logging
from twilio.rest import Client
from datetime import datetime, timedelta
from models import Assignment,Submission,User

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def send_sms_notification(user_id, message):
    """Send SMS notification to a user"""
    try:
        # Get Twilio credentials from environment
        account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
        auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
        from_number = os.environ.get('TWILIO_PHONE_NUMBER')
        
        if not all([account_sid, auth_token, from_number]):
            logger.error("Missing Twilio credentials")
            return False
        
        # Get user's phone number
        user = User.query.get(user_id)
        if not user or not user.phone_number:
            logger.error(f"No phone number found for user {user_id}")
            return False
        
        # Initialize Twilio client
        client = Client(account_sid, auth_token)
        
        # Send message
        client.messages.create(
            body=message,
            from_=from_number,
            to=user.phone_number
        )
        logger.info(f"SMS notification sent to user {user_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error sending SMS notification: {str(e)}")
        return False

def notify_new_assignment(assignment):
    """Notify all students when a new assignment is created"""
    students = User.query.filter_by(role='student').all()
    message = f"New Assignment: {assignment.title}\nDue Date: {assignment.due_date.strftime('%Y-%m-%d %H:%M')}"
    
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
    
def check_approaching_deadlines():
    """Check for assignments due in 24 hours and notify students"""    
    now = datetime.utcnow()    
    tomorrow = now + timedelta(days=1)

    # Find assignments due in the next 24 hours
    approaching_assignments = Assignment.query.filter(
        Assignment.due_date > now,
        Assignment.due_date <= tomorrow
    ).all()

    students = User.query.filter_by(role='student').all()

    for assignment in approaching_assignments:
        message = f"REMINDER: Assignment '{assignment.title}' is due in less than 24 hours ({assignment.due_date.strftime('%Y-%m-%d %H:%M')})"
        for student in students:
            # Check if student hasn't submitted yet
            if not Submission.query.filter_by(assignment_id=assignment.id, student_id=student.id).first():
                send_sms_notification(student.id, message)
