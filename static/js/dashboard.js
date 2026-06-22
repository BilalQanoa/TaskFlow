document.addEventListener('DOMContentLoaded', function () {
    let progressLabels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'];
    let progressPoints = [40, 58, 70, 82, 88, 96];
    let tasksStatusData = [12, 8, 4];
    let tasksStatusLabels = ['Completed', 'In Progress', 'Pending'];
    let tasksStatusColors = ['#2563EB', '#06B6D4', '#F59E0B'];

    const chartDataEl = document.getElementById('chart-data');
    if (chartDataEl) {
        try {
            const chartData = JSON.parse(chartDataEl.textContent);
            if (chartData.progressLabels && chartData.progressLabels.length >= 0) {
                progressLabels = chartData.progressLabels;
            }
            if (chartData.progressPoints && chartData.progressPoints.length >= 0) {
                progressPoints = chartData.progressPoints;
            }
            if (chartData.tasksStatusData && chartData.tasksStatusData.length >= 0) {
                tasksStatusData = chartData.tasksStatusData;
                
                // Fallback handling when no tasks exist
                const totalTasks = tasksStatusData.reduce((a, b) => a + b, 0);
                if (totalTasks === 0) {
                    tasksStatusData = [1];
                    tasksStatusLabels = ['No Tasks Available'];
                    tasksStatusColors = ['#E2E8F0']; // Gray placeholder color
                }
            }
        } catch (e) {
            console.error("Failed to parse chart data JSON", e);
        }
    }

    const progressCtx = document.getElementById('projectProgressChart');
    if (progressCtx && window.Chart) {
        new Chart(progressCtx, {
            type: 'line',
            data: {
                labels: progressLabels,
                datasets: [{
                    label: 'Completion %',
                    data: progressPoints,
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
                labels: tasksStatusLabels,
                datasets: [{
                    data: tasksStatusData,
                    backgroundColor: tasksStatusColors,
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
