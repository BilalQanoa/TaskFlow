document.addEventListener('DOMContentLoaded', function () {
    const progressCtx = document.getElementById('projectProgressChart');
    if (progressCtx && window.Chart) {
        new Chart(progressCtx, {
            type: 'line',
            data: {
                labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
                datasets: [{
                    label: 'Completion %',
                    data: [40, 58, 70, 82, 88, 96],
                    borderColor: '#2563EB',
                    backgroundColor: 'rgba(37, 99, 235, 0.12)',
                    fill: true,
                    tension: 0.35,
                    pointBackgroundColor: '#06B6D4',
                    pointBorderColor: '#fff',
                    pointRadius: 4,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 0 },
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, max: 100, grid: { color: 'rgba(148,163,184,0.18)' } },
                    x: { grid: { display: false } },
                }
            }
        });
    }

    const statusCtx = document.getElementById('taskStatusChart');
    if (statusCtx && window.Chart) {
        new Chart(statusCtx, {
            type: 'doughnut',
            data: {
                labels: ['Completed', 'In Progress', 'Pending'],
                datasets: [{
                    data: [12, 8, 4],
                    backgroundColor: ['#2563EB', '#06B6D4', '#F59E0B'],
                    borderWidth: 0,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 0 },
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { padding: 16, usePointStyle: true, color: '#475569' }
                    }
                },
                cutout: '70%'
            }
        });
    }
});
