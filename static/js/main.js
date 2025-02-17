// File upload validation and UI enhancements
document.addEventListener('DOMContentLoaded', function() {
    // Initialize all feather icons
    if (typeof feather !== 'undefined') {
        feather.replace();
    }

    // File upload validation
    const fileInputs = document.querySelectorAll('input[type="file"]');
    fileInputs.forEach(input => {
        input.addEventListener('change', function(e) {
            const file = e.target.files[0];
            if (file) {
                // Check file type
                const allowedTypes = ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain'];
                if (!allowedTypes.includes(file.type)) {
                    alert('Please upload only PDF, DOCX, or TXT files');
                    e.target.value = '';
                    return;
                }

                // Check file size (max 10MB)
                if (file.size > 10 * 1024 * 1024) {
                    alert('File size should not exceed 10MB');
                    e.target.value = '';
                    return;
                }
            }
        });
    });

    // DateTime input default value setter
    const dueDateInput = document.querySelector('#due_date');
    if (dueDateInput) {
        // Set minimum date to current date/time
        const now = new Date();
        const offset = now.getTimezoneOffset();
        const localDateTime = new Date(now.getTime() - (offset * 60 * 1000))
            .toISOString()
            .slice(0, 16);
        dueDateInput.min = localDateTime;

        // If no value is set, default to 7 days from now
        if (!dueDateInput.value) {
            const defaultDate = new Date(now.getTime() + (7 * 24 * 60 * 60 * 1000));
            const defaultDateTime = new Date(defaultDate.getTime() - (offset * 60 * 1000))
                .toISOString()
                .slice(0, 16);
            dueDateInput.value = defaultDateTime;
        }
    }

    // Alert auto-dismiss
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000);
    });

    // Form validation
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            if (!form.checkValidity()) {
                e.preventDefault();
                e.stopPropagation();
            }
            form.classList.add('was-validated');
        });
    });

    // Assignment submission progress
    const submitButtons = document.querySelectorAll('button[type="submit"]');
    submitButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            const form = this.closest('form');
            if (form && form.checkValidity()) {
                this.disabled = true;
                this.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Submitting...';
            }
        });
    });
});

function updateDueDate(event, assignmentId) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    const modal = document.getElementById(`updateDueDate${assignmentId}`);
    const modalInstance = bootstrap.Modal.getInstance(modal);

    fetch(`/assignment/${assignmentId}/update-due-date`, {
        method: 'POST',
        body: formData
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        return response.json();
    })
    .then(data => {
        if (data.success) {
            modalInstance.hide();
            alert('Due date updated successfully');
            location.reload();
        } else {
            alert(data.error || 'Error updating due date');
        }
    })
    .catch(error => {
        alert('Error updating due date');
        console.error('Error:', error);
    });
}