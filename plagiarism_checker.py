from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from models import Submission, PlagiarismResult, Assignment
from app import db
import PyPDF2
import docx
import logging

def extract_text_from_file(file_path):
    """Extract text content from various file formats"""
    try:
        if file_path.endswith('.txt'):
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        elif file_path.endswith('.pdf'):
            text = ""
            with open(file_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                for page in pdf_reader.pages:
                    text += page.extract_text()
            return text
        elif file_path.endswith('.docx'):
            doc = docx.Document(file_path)
            return ' '.join([paragraph.text for paragraph in doc.paragraphs])
        return ""
    except Exception as e:
        logging.error(f"Error extracting text from {file_path}: {str(e)}")
        return ""

def check_plagiarism(assignment_id):
    """Check plagiarism for all submissions of an assignment"""
    submissions = Submission.query.filter_by(assignment_id=assignment_id).all()
    
    if len(submissions) < 2:
        return
    
    # Create TF-IDF vectors
    vectorizer = TfidfVectorizer()
    vectors = vectorizer.fit_transform([s.content_text for s in submissions])
    
    # Calculate similarity matrix
    similarity_matrix = cosine_similarity(vectors)
    
    # Create plagiarism results
    for i in range(len(submissions)):
        for j in range(i + 1, len(submissions)):
            similarity_score = similarity_matrix[i][j]
            
            if similarity_score > 0.3:  # Threshold for similarity
                result = PlagiarismResult(
                    assignment_id=assignment_id,
                    student1_id=submissions[i].student_id,
                    student2_id=submissions[j].student_id,
                    similarity_score=float(similarity_score),
                    matched_content="Similarity detected in submission"
                )
                db.session.add(result)
    
    # Mark assignment as checked
    assignment = Assignment.query.get(assignment_id)
    assignment.is_checked = True
    
    db.session.commit()
