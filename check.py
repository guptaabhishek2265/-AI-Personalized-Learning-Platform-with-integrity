from fpdf import FPDF
import os
import re
from itertools import combinations

class PDF(FPDF):
    def header(self):
        self.set_fill_color(0, 102, 204)  # Blue header
        self.set_text_color(255, 255, 255)
        self.set_font("DejaVu", "B", 14)
        self.cell(0, 10, "Plagiarism Detection Report", border=0, ln=1, align="C", fill=True)
        self.ln(5)

def register_fonts(pdf):
    base_path = "static/fonts/ttf"
    pdf.add_font("DejaVu", "", os.path.join(base_path, "DejaVuSans.ttf"), uni=True)
    pdf.add_font("DejaVu", "B", os.path.join(base_path, "DejaVuSans-Bold.ttf"), uni=True)

def calculate_similarity(text1, text2):
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    common_words = words1 & words2
    total_unique_words = len(words1 | words2)
    if total_unique_words == 0:
        return 0, common_words
    similarity = (len(common_words) / total_unique_words) * 100
    return similarity, common_words

def find_plagiarism_groups(texts, threshold=50):
    similarities = []
    n = len(texts)
    for i, j in combinations(range(n), 2):
        similarity, common_words = calculate_similarity(texts[i], texts[j])
        if similarity >= threshold:
            similarities.append((i, j, similarity, common_words))
    
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
    
    return similarities, groups

def render_text(pdf, x, y, text, matched_words, col_width, title):
    # Draw a shaded box
    pdf.set_fill_color(240, 240, 240)  # Light gray background
    pdf.set_xy(x, y)
    # Estimate box height based on text length
    line_height = 6
    lines = sum(1 for i in range(0, len(text), 40))
    box_height = lines * line_height + 20
    # Ensure the box fits on the page
    if y + box_height > pdf.page_break_trigger:
        pdf.add_page()
        y = 20  # Reset y position after adding a new page
        pdf.set_xy(x, y)
    pdf.rect(x, y, col_width, box_height, style="DF")

    # Title
    pdf.set_xy(x + 2, y + 2)
    pdf.set_font("DejaVu", "B", 10)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(col_width - 4, 6, title, ln=1)

    # Render text with highlighted words
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

def generate_plagiarism_report(texts):
    if not texts or all(t == "" for t in texts):
        print("No valid texts provided.")
        return

    # Find plagiarism groups
    similarities, groups = find_plagiarism_groups(texts, threshold=50)

    pdf = PDF()
    register_fonts(pdf)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Summary of findings
    pdf.set_font("DejaVu", "B", 12)
    pdf.cell(0, 10, f"Summary of Plagiarism Findings ({len(texts)} Documents)", ln=1)
    pdf.ln(5)

    if not groups:
        pdf.set_font("DejaVu", "", 10)
        pdf.cell(0, 10, "No significant plagiarism detected (similarity < 50%).", ln=1)
    else:
        pdf.set_font("DejaVu", "", 10)
        pdf.cell(0, 10, f"Detected {len(groups)} groups of potential plagiarism:", ln=1)
        pdf.ln(5)

        col_width = 90
        gutter = 10
        x_left = 10
        x_right = x_left + col_width + gutter

        for idx, (group, sim, common_words) in enumerate(groups, 1):
            pdf.set_font("DejaVu", "B", 10)
            pdf.cell(0, 8, f"Group {idx} (Similarity: {sim:.2f}%):", ln=1)
            pdf.set_font("DejaVu", "", 9)
            pdf.cell(0, 6, f"Documents: {', '.join(f'Document {i+1}' for i in sorted(group))}", ln=1)
            pdf.cell(0, 6, f"Common Words: {', '.join(sorted(common_words))}", ln=1)
            pdf.ln(5)

            # Display the texts in the group
            for i, doc_idx in enumerate(sorted(group)):
                x_pos = x_left if i % 2 == 0 else x_right
                y_top = pdf.get_y()
                y_after = render_text(pdf, x_pos, y_top, texts[doc_idx], common_words, col_width, f"Document {doc_idx+1}")
                if i % 2 == 1 or i == len(group) - 1:
                    pdf.set_y(y_after + 10)

    # Add a legend
    pdf.ln(5)
    pdf.set_font("DejaVu", "", 8)
    pdf.set_fill_color(255, 204, 204)
    pdf.cell(10, 5, "", fill=True, ln=0)
    pdf.cell(5, 5, "", ln=0)
    pdf.cell(0, 5, "Highlighted text indicates matching words", ln=1)

    pdf.output("plagiarism_report_sample.pdf")
    print("✅ Report generated: plagiarism_report_sample.pdf")

# Example input: 22 texts
texts = [
    "Binary search works by repeatedly dividing the search interval in half to find the target.",
    "Binary search algorithm divides the range in half until the target is found or the interval is empty.",
    "The binary search method splits the interval in half repeatedly to locate the target.",
    "Binary search repeatedly divides the interval in half to find the target efficiently.",
    "Sorting algorithms can be complex but are efficient for large datasets like quicksort.",
    "Binary search is a method that splits the range in half repeatedly to find the target.",
    "Quicksort is an efficient sorting algorithm for large datasets with good average performance.",
    "Binary search divides the interval in half repeatedly to locate the target value.",
    "Sorting large datasets can be done efficiently using the quicksort algorithm.",
    "Binary search algorithm splits the interval in half to find the target quickly.",
    "Merge sort is a stable sorting algorithm that divides the array into smaller parts.",
    "Binary search works by dividing the search range in half until the target is found.",
    "Quicksort algorithm is highly efficient for sorting large datasets on average.",
    "The binary search technique repeatedly splits the interval to find the target.",
    "Sorting with quicksort is efficient for large datasets and has good performance.",
    "Binary search method divides the range in half to locate the target efficiently.",
    "Heap sort is an in-place sorting algorithm that uses a binary heap structure.",
    "Binary search splits the search interval in half repeatedly to find the target.",
    "Quicksort is a fast sorting algorithm for large datasets with excellent performance.",
    "Binary search algorithm divides the interval in half repeatedly to find the target.",
    "Sorting algorithms like quicksort are efficient for large datasets and widely used.",
    "The binary search process splits the range in half to locate the target value."
]

generate_plagiarism_report(texts)