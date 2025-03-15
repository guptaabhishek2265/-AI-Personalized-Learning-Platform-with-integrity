// File upload validation and UI enhancements
document.addEventListener("DOMContentLoaded", function () {
  // Initialize all feather icons
  if (typeof feather !== "undefined") {
    feather.replace();
  }
  
  // File upload validation
  const fileInputs = document.querySelectorAll('input[type="file"]');
  fileInputs.forEach((input) => {
    input.addEventListener("change", function (e) {
      const file = e.target.files[0];
      if (file) {
        // Check file type
        const allowedTypes = [
          "application/pdf",
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          "text/plain",
        ];
        if (!allowedTypes.includes(file.type)) {
          alert("Please upload only PDF, DOCX, or TXT files");
          e.target.value = "";
          return;
        }
        // Check file size (max 10MB)
        if (file.size > 10 * 1024 * 1024) {
          alert("File size should not exceed 10MB");
          e.target.value = "";
          return;
        }
      }
    });
  });

  // DateTime input default value setter with IST
  const dueDateInput = document.querySelector("#due_date");
  if (dueDateInput) {
    // Get current UTC time and adjust to IST (UTC+5:30)
    const nowUtc = new Date();
    const istOffset = 5.5 * 60 * 60 * 1000; // 5 hours 30 minutes in milliseconds
    const nowIst = new Date(nowUtc.getTime() + istOffset);

    // Set minimum date to current IST date/time
    const localDateTime = nowIst.toISOString().slice(0, 16);
    dueDateInput.min = localDateTime;

    // If no value is set, default to 7 days from now in IST
    if (!dueDateInput.value) {
      const defaultDate = new Date(nowIst.getTime() + 7 * 24 * 60 * 60 * 1000);
      const defaultDateTime = defaultDate.toISOString().slice(0, 16);
      dueDateInput.value = defaultDateTime;
    }
  }

  // Alert auto-dismiss
  const alerts = document.querySelectorAll(".alert");
  alerts.forEach((alert) => {
    setTimeout(() => {
      const bsAlert = new bootstrap.Alert(alert);
      bsAlert.close();
    }, 5000);
  });

  // Form validation
  const forms = document.querySelectorAll("form");
  forms.forEach((form) => {
    form.addEventListener("submit", function (e) {
      if (!form.checkValidity()) {
        e.preventDefault();
        e.stopPropagation();
      }
      form.classList.add("was-validated");
    });
  });

  // Assignment submission progress
  const submitButtons = document.querySelectorAll('button[type="submit"]');
  submitButtons.forEach((button) => {
    button.addEventListener("click", function (e) {
      const form = this.closest("form");
      if (form && form.checkValidity()) {
        this.disabled = true;
        this.innerHTML =
          '<span class="spinner-border spinner-border-sm"></span> Submitting...';
      }
    });
  });
});

function updateDueDate(event, assignmentId) {
  event.preventDefault();
  const form = event.target;
  const formData = new FormData(form);
  const newDueDate = form.querySelector('input[name="new_due_date"]').value;

  console.log('Updating due date for assignment:', assignmentId);
  console.log('New due date:', newDueDate);

  if (!newDueDate || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(newDueDate)) {
    alert('Please enter a valid date in YYYY-MM-DDTHH:MM format.');
    return;
  }

  fetch(`/assignment/${assignmentId}/update-due-date`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded'
    },
    body: new URLSearchParams({ new_due_date: newDueDate })
  })
    .then(response => {
      console.log('Response status:', response.status);
      if (!response.ok) {
        throw new Error(`HTTP error! Status: ${response.status}`);
      }
      return response.json();
    })
    .then(data => {
      console.log('Response data:', data);
      if (data.success) {
        alert('Due date updated successfully');
        const modalElement = document.getElementById(`updateDueDate${assignmentId}`);
        const modal = bootstrap.Modal.getInstance(modalElement) || new bootstrap.Modal(modalElement);
        modal.hide(); // Close the modal
        location.reload(); // Refresh the page
      } else {
        alert(data.error || 'Error updating due date');
      }
    })
    .catch(error => {
      console.error('Fetch error:', error);
      alert('Error updating due date: ' + error.message);
    });
}