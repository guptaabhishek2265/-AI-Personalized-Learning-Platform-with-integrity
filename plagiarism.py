import os
import requests
import time
from datetime import datetime
import docx
import numpy as np
from werkzeug.utils import secure_filename,safe_join
import textdistance
import matplotlib.pyplot as plt
from sklearn.feature_extraction.text import TfidfVectorizer
import csv
from fpdf import FPDF
from flask import current_app
from app import db
from models import Assignment, Submission, PlagiarismResult, User
from pytz import timezone
from services.notification import (
    notify_plagiarism_report
)
IST = timezone('Asia/Kolkata')

# 🔑 API Configuration
API_KEY = "XsFNTlH-zhhLEjKd7898s_9rpFe7ozxTdYs_rE-rmGU"  # Replace with your actual API key
BASE_URL = "https://llmwhisperer-api.us-central.unstract.com/api/v2"

def upload_file(file_path):
    """Uploads a file to the API and returns the whisper_hash."""
    url = f"{BASE_URL}/whisper?mode=form&output_mode=layout_preserving"
    headers = {"Content-Type": "application/octet-stream", "unstract-key": API_KEY}
    
    try:
        with open(file_path, "rb") as file:
            response = requests.post(url, headers=headers, data=file)
            data = response.json()

        if "whisper_hash" in data:
            whisper_hash = data["whisper_hash"]
            current_app.logger.info(f"✅ File uploaded successfully! Whisper Hash: {whisper_hash}")
            return whisper_hash
        else:
            current_app.logger.error(f"❌ Error uploading file: {data}")
            return None
    except Exception as e:
        current_app.logger.error(f"❌ Exception during file upload: {e}")
        return None

def check_status(whisper_hash):
    """Checks if the uploaded file has been processed."""
    status_url = f"{BASE_URL}/whisper-status?whisper_hash={whisper_hash}"
    headers = {"unstract-key": API_KEY}
    
    while True:
        response = requests.get(status_url, headers=headers)
        try:
            data = response.json()
        except requests.exceptions.JSONDecodeError:
            current_app.logger.error(f"❌ Error decoding JSON response: {response.text}")
            return False

        status = data.get("status", "unknown")
        current_app.logger.info(f"⏳ Processing status: {status}")

        if status == "processed":
            return True
        elif status in ["failed", "error"]:
            current_app.logger.error(f"❌ Processing failed: {data}")
            return False
        else:
            time.sleep(5)

def retrieve_text(whisper_hash):
    """Retrieves extracted text from the processed file."""
    retrieve_url = f"{BASE_URL}/whisper-retrieve?whisper_hash={whisper_hash}&text_only=true"
    headers = {"unstract-key": API_KEY}
    response = requests.get(retrieve_url, headers=headers)
    if response.status_code != 200:
        current_app.logger.error(f"❌ Failed to retrieve text. Status Code: {response.status_code}")
        return None
    try:
        data = response.json()
        extracted_text = data.get("text", "").strip()
        return extracted_text
    except requests.exceptions.JSONDecodeError:
        return response.text.strip()

def extract_text(file_path):
    """Extracts text from various file formats including .txt, .pdf, .docx, .png, and .jpg."""
    text = ""
    if file_path.endswith(".txt"):
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read().strip()
    elif file_path.endswith((".png", ".jpg", ".jpeg", ".pdf")):
        whisper_hash = upload_file(file_path)
        if whisper_hash and check_status(whisper_hash):
            text = retrieve_text(whisper_hash)
    elif file_path.endswith(".docx"):
        doc = docx.Document(file_path)
        text = " ".join([para.text.strip() for para in doc.paragraphs])
    # Clean text
    text = " ".join(text.split())  # Remove extra spaces and newlines
    text = text.encode("utf-8", "ignore").decode("utf-8")  # Handle encoding issues
    current_app.logger.info(f"Extracted text from {file_path}: {text[:50]}...")
    return text

def calculate_similarity(text1, text2):
    """Calculates Cosine, Jaccard, and Levenshtein similarity scores between two texts."""
    text1, text2 = text1.strip(), text2.strip()

    if not text1 or not text2:
        current_app.logger.warning("⚠ One or both documents are empty. Skipping similarity calculation.")
        return 0, 0, 0

    vectorizer = TfidfVectorizer(stop_words=None)
    try:
        tfidf_matrix = vectorizer.fit_transform([text1, text2])
        cosine_sim = (tfidf_matrix * tfidf_matrix.T).toarray()[0, 1] * 100
    except ValueError:
        cosine_sim = 0  # No meaningful words for vectorization

    words1, words2 = set(text1.split()), set(text2.split())
    jaccard_sim = (len(words1 & words2) / len(words1 | words2)) * 100 if words1 | words2 else 0

    levenshtein_sim = (1 - textdistance.levenshtein.normalized_distance(text1, text2)) * 100

    return round(cosine_sim, 2), round(jaccard_sim, 2), round(levenshtein_sim, 2)

def generate_pdf_report(assignment_id, file_pairs, scores, texts):
    """Generate PDF report for the assignment."""
    upload_dir = current_app.config['UPLOAD_FOLDER']
    report_path = os.path.join(upload_dir, f"plagiarism_report_{assignment_id}.pdf")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", style="B", size=16)
    pdf.add_page()
    pdf.cell(200, 10, f"Plagiarism Report for Assignment {assignment_id}", ln=True, align='C')
    pdf.ln(10)
    
    for (student1, student2), (cosine, jaccard, levenshtein) in zip(file_pairs, scores):
        pdf.set_font("Arial", style="B", size=14)
        pdf.cell(200, 10, f"{student1.username} vs {student2.username}", ln=True)
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 10, f"Cosine Similarity: {cosine}%", ln=True)
        pdf.cell(200, 10, f"Jaccard Similarity: {jaccard}%", ln=True)
        pdf.cell(200, 10, f"Levenshtein Similarity: {levenshtein}%", ln=True)
        pdf.ln(5)
        
        words1, words2 = set(texts[student1.id].split()), set(texts[student2.id].split())
        matched_words = words1 & words2
        
        pdf.set_font("Arial", style="B", size=12)
        pdf.cell(200, 10, "Matched Words:", ln=True)
        pdf.set_font("Arial", size=10)
        pdf.multi_cell(0, 10, " ".join(matched_words))
        pdf.ln(10)
    
    pdf.output(report_path)
    return report_path

def plot_similarity_scores(assignment_id, scores, file_pairs):
    """Plots the similarity scores."""
    upload_dir = current_app.config['UPLOAD_FOLDER']
    graph_path = os.path.join(upload_dir, f"plagiarism_graph_{assignment_id}.png")

    labels = [f"{student1.username} & {student2.username}" for student1, student2 in file_pairs]
    cosine, jaccard, levenshtein = zip(*scores)
    
    x = np.arange(len(labels))
    width = 0.2
    
    plt.figure(figsize=(10, 5))
    plt.bar(x - width, cosine, width, label="Cosine")
    plt.bar(x, jaccard, width, label="Jaccard")
    plt.bar(x + width, levenshtein, width, label="Levenshtein")
    
    plt.ylabel("Similarity (%)")
    plt.xlabel("Student Pairs")
    plt.xticks(x, labels, rotation=45, ha="right")
    plt.legend()
    plt.title(f"Plagiarism Similarity Scores for Assignment {assignment_id}")
    plt.tight_layout()
    plt.savefig(graph_path)
    plt.close()
    
    return graph_path

def check_plagiarism(assignment_id):
    current_app.logger.info(f"Starting plagiarism check for assignment {assignment_id}")
    assignment = Assignment.query.get_or_404(assignment_id)
    now_ist = datetime.now(IST)
    current_app.logger.info(f"Current time: {now_ist}, Due date: {assignment.due_date}")

    submissions = Submission.query.filter_by(assignment_id=assignment_id).all()
    current_app.logger.info(f"Found {len(submissions)} submissions")
    if len(submissions) < 2:
        current_app.logger.info("Fewer than 2 submissions, skipping")
        return

    # Extract texts
    texts = {}
    for submission in submissions:
        file_path = safe_join(current_app.config['UPLOAD_FOLDER'], submission.file_path)
        text = extract_text(file_path)
        texts[submission.student_id] = text
        submission.content_text = text
        current_app.logger.info(f"Extracted text for student {submission.student_id}: {text[:50]}...")
    db.session.commit()

    scores = []
    file_pairs = []
    results = []

    for i, sub1 in enumerate(submissions):
        for sub2 in submissions[i + 1:]:
            student1 = User.query.get(sub1.student_id)
            student2 = User.query.get(sub2.student_id)
            cosine, jaccard, levenshtein = calculate_similarity(texts[sub1.student_id], texts[sub2.student_id])
            avg_similarity = (cosine + jaccard + levenshtein) / 3
            current_app.logger.info(f"{student1.username} vs {student2.username}: {avg_similarity}%")

            if avg_similarity > 10:  # Threshold
                # Calculate matched content (intersection of words)
                words1 = set(texts[sub1.student_id].split())
                words2 = set(texts[sub2.student_id].split())
                matched_content = " ".join(words1 & words2)  # Common words
                matched_content = "your long matched content here"  # Example long string
                truncated_content = matched_content[:255]
                scores.append((cosine, jaccard, levenshtein))
                file_pairs.append((student1, student2))
                result = PlagiarismResult(
                    assignment_id=assignment_id,
                    student1_id=sub1.student_id,
                    student2_id=sub2.student_id,
                    similarity_score=avg_similarity,
                    matched_content=truncated_content,
                    report_path=None,
                    graph_path=None
                )
                results.append(result)
                db.session.add(result)

    if scores:
        report_path = generate_pdf_report(assignment_id, file_pairs, scores, texts)
        graph_path = plot_similarity_scores(assignment_id, scores, file_pairs)
        for result in results:
            result.report_path = report_path
            result.graph_path = graph_path
        db.session.commit()
        
        current_app.logger.info(f"Plagiarism check completed, report and graph generated")
        notify_plagiarism_report(assignment)
    else:
        current_app.logger.info("No significant plagiarism detected")