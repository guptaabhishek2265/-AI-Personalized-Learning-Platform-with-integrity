import os
import requests
import time
from datetime import datetime
import docx
import numpy as np
from werkzeug.utils import secure_filename, safe_join
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
from itertools import combinations

IST = timezone('Asia/Kolkata')

# 🔑 API Configuration
API_KEY = "u8qY3SzXNxkg2AycVM3dOyP_t_vdpljhl5o7WBTl030"  # Replace with your actual API key
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

def register_all_dejavu_fonts(pdf):
    base_path = 'static/fonts/ttf'
    try:
        pdf.add_font('DejaVu', '', os.path.join(base_path, 'DejaVuSans.ttf'), uni=True)
        pdf.add_font('DejaVu', 'B', os.path.join(base_path, 'DejaVuSans-Bold.ttf'), uni=True)
        pdf.add_font('DejaVuMono', '', os.path.join(base_path, 'DejaVuSansMono.ttf'), uni=True)
    except Exception as e:
        print(f"⚠️ Error loading font: {e}")

def generate_pdf_report(assignment_id, file_pairs, scores, texts):
    """Generate Unicode-compatible PDF report for the assignment with grouped plagiarism results and truncated text."""
    
    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'results')
    os.makedirs(upload_dir, exist_ok=True)
    
    report_path = os.path.join(upload_dir, f"plagiarism_report_{assignment_id}.pdf")

    # Custom PDF class for header
    class PDFWithHeader(FPDF):
        def header(self):
            self.set_fill_color(0, 102, 204)  # Blue header
            self.set_text_color(255, 255, 255)
            self.set_font("DejaVu", "B", 14)
            self.cell(0, 10, f"Plagiarism Detection Report - Assignment {assignment_id}", border=0, ln=1, align="C", fill=True)
            self.ln(5)

    pdf = PDFWithHeader()
    register_all_dejavu_fonts(pdf)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Step 1: Prepare texts list and map student IDs to indices
    student_ids = list(texts.keys())
    texts_list = [texts[sid] for sid in student_ids]
    student_id_to_index = {sid: idx for idx, sid in enumerate(student_ids)}

    # Step 2: Group submissions by similarity
    def find_plagiarism_groups(scores, file_pairs, threshold=10):
        similarities = []
        for (student1, student2), (cosine, jaccard, levenshtein) in zip(file_pairs, scores):
            avg_similarity = (cosine + jaccard + levenshtein) / 3
            if avg_similarity >= threshold:
                idx1 = student_id_to_index[student1.id]
                idx2 = student_id_to_index[student2.id]
                words1, words2 = set(texts[student1.id].split()), set(texts[student2.id].split())
                common_words = words1 & words2
                similarities.append((idx1, idx2, avg_similarity, common_words))
        
        # Group texts with high similarity
        groups = []
        used = set()
        for i, j, sim, common in similarities:
            if i in used or j in used:
                continue
            group = {i, j}
            used.update(group)
            for k, l, sim2, _ in similarities:
                if k in group or l in group:
                    group.add(k)
                    group.add(l)
                    used.update({k, l})
            groups.append((group, sim, common))
        
        return groups

    groups = find_plagiarism_groups(scores, file_pairs, threshold=10)

    # Step 3: Generate the report
    pdf.set_font("DejaVu", "B", 12)
    pdf.cell(0, 10, f"Summary of Plagiarism Findings ({len(texts_list)} Submissions)", ln=1)
    pdf.ln(5)

    if not groups:
        pdf.set_font("DejaVu", "", 10)
        pdf.cell(0, 10, "No significant plagiarism detected (similarity < 10%).", ln=1)
    else:
        pdf.set_font("DejaVu", "", 10)
        pdf.cell(0, 10, f"Detected {len(groups)} groups of potential plagiarism:", ln=1)
        pdf.ln(5)

        col_width = 90
        gutter = 10
        x_left = 10
        x_right = x_left + col_width + gutter

        def render_text(pdf, x, y, text, matched_words, col_width, title):
            # Truncate text to 200 characters
            max_chars = 200
            if len(text) > max_chars:
                text = text[:max_chars].rsplit(" ", 1)[0] + "..."

            pdf.set_fill_color(240, 240, 240)  # Light gray background
            pdf.set_xy(x, y)
            line_height = 6
            # Estimate lines based on truncated text
            lines = sum(1 for i in range(0, len(text), 40))
            box_height = lines * line_height + 20
            if y + box_height > pdf.page_break_trigger:
                pdf.add_page()
                y = 20
                pdf.set_xy(x, y)
            pdf.rect(x, y, col_width, box_height, style="DF")

            pdf.set_xy(x + 2, y + 2)
            pdf.set_font("DejaVu", "B", 10)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(col_width - 4, 6, title, ln=1)

            pdf.set_xy(x + 2, pdf.get_y())
            words = text.split()
            line_height = 6
            current_y = pdf.get_y()
            buffer = []

            for i, word in enumerate(words):
                is_matched = word.lower() in matched_words
                pdf.set_fill_color(255, 204, 204) if is_matched else pdf.set_fill_color(240, 240, 240)
                pdf.set_font("DejaVu", "B" if is_matched else "", 9)
                buffer.append((word, is_matched))
                
                if i == len(words) - 1 or pdf.get_string_width(" ".join(w[0] for w in buffer)) > col_width - 4:
                    pdf.set_xy(x + 2, current_y)
                    for w, matched in buffer:
                        pdf.set_fill_color(255, 204, 204) if matched else pdf.set_fill_color(240, 240, 240)
                        pdf.set_font("DejaVu", "B" if matched else "", 9)
                        pdf.cell(pdf.get_string_width(w + " "), line_height, w + " ", fill=matched, ln=0)
                    current_y += line_height
                    if current_y > pdf.page_break_trigger:
                        pdf.add_page()
                        current_y = 20
                        pdf.set_xy(x + 2, current_y)
                    buffer = []

            return current_y + line_height

        for idx, (group, sim, common_words) in enumerate(groups, 1):
            pdf.set_font("DejaVu", "B", 10)
            pdf.cell(0, 8, f"Group {idx} (Similarity: {sim:.2f}%):", ln=1)
            pdf.set_font("DejaVu", "", 9)
            group_student_ids = [student_ids[i] for i in group]
            student_names = [User.query.get(sid).username for sid in group_student_ids]
            pdf.cell(0, 6, f"Students: {', '.join(student_names)}", ln=1)
            pdf.cell(0, 6, f"Common Words: {', '.join(sorted(common_words))}", ln=1)
            pdf.ln(5)

            for i, doc_idx in enumerate(sorted(group)):
                student_id = student_ids[doc_idx]
                student_name = User.query.get(student_id).username
                x_pos = x_left if i % 2 == 0 else x_right
                y_top = pdf.get_y()
                y_after = render_text(pdf, x_pos, y_top, texts[student_id], common_words, col_width, f"{student_name}")
                if i % 2 == 1 or i == len(group) - 1:
                    pdf.set_y(y_after + 10)

    # Add a legend
    pdf.ln(5)
    pdf.set_font("DejaVu", "", 8)
    pdf.set_fill_color(255, 204, 204)
    pdf.cell(10, 5, "", fill=True, ln=0)
    pdf.cell(5, 5, "", ln=0)
    pdf.cell(0, 5, "Highlighted text indicates matching words", ln=1)

    pdf.output(report_path)
    return report_path

def plot_similarity_scores(assignment_id, scores, file_pairs):
    """Plots the similarity scores."""
    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'results')
    os.makedirs(upload_dir, exist_ok=True)

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