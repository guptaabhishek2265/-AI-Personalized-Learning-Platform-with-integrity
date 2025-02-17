// Chart utility functions for plagiarism visualization
const ChartUtils = {
    // Colors for different similarity levels
    colors: {
        high: '#dc3545',    // Bootstrap danger
        moderate: '#ffc107', // Bootstrap warning
        low: '#198754',      // Bootstrap success
        background: '#2c3338' // Dark theme background
    },

    // Create a similarity distribution chart
    createSimilarityChart: function(canvasId, data) {
        const ctx = document.getElementById(canvasId).getContext('2d');
        
        return new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: ['High Similarity (>80%)', 'Moderate (50-80%)', 'Low (<50%)'],
                datasets: [{
                    data: data,
                    backgroundColor: [
                        this.colors.high,
                        this.colors.moderate,
                        this.colors.low
                    ],
                    borderColor: this.colors.background,
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            color: '#ffffff',
                            padding: 20,
                            font: {
                                size: 12
                            }
                        }
                    },
                    title: {
                        display: true,
                        text: 'Similarity Distribution',
                        color: '#ffffff',
                        font: {
                            size: 16,
                            weight: 'bold'
                        },
                        padding: {
                            top: 10,
                            bottom: 30
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const label = context.label || '';
                                const value = context.raw || 0;
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = Math.round((value / total) * 100);
                                return `${label}: ${value} (${percentage}%)`;
                            }
                        }
                    }
                }
            }
        });
    },

    // Create a timeline chart for submissions
    createSubmissionTimeline: function(canvasId, labels, submissions) {
        const ctx = document.getElementById(canvasId).getContext('2d');
        
        return new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Submissions',
                    data: submissions,
                    borderColor: this.colors.moderate,
                    backgroundColor: this.colors.moderate + '40',
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                scales: {
                    x: {
                        grid: {
                            color: '#ffffff20'
                        },
                        ticks: {
                            color: '#ffffff'
                        }
                    },
                    y: {
                        beginAtZero: true,
                        grid: {
                            color: '#ffffff20'
                        },
                        ticks: {
                            color: '#ffffff'
                        }
                    }
                },
                plugins: {
                    legend: {
                        display: false
                    },
                    title: {
                        display: true,
                        text: 'Submission Timeline',
                        color: '#ffffff',
                        font: {
                            size: 16,
                            weight: 'bold'
                        }
                    }
                }
            }
        });
    },

    // Format percentage for display
    formatPercentage: function(value) {
        return `${(value * 100).toFixed(1)}%`;
    },

    // Get color based on similarity score
    getColorForSimilarity: function(score) {
        if (score > 0.8) return this.colors.high;
        if (score > 0.5) return this.colors.moderate;
        return this.colors.low;
    },

    // Create gradient for chart backgrounds
    createGradient: function(ctx, startColor, endColor) {
        const gradient = ctx.createLinearGradient(0, 0, 0, 400);
        gradient.addColorStop(0, startColor);
        gradient.addColorStop(1, endColor);
        return gradient;
    }
};
