document.addEventListener('DOMContentLoaded', function () {
    const toasts = document.querySelectorAll('.toast-alert');
    toasts.forEach(function (toast) {
        setTimeout(function () {
            toast.classList.add('toast-alert--dismiss');
            setTimeout(function () {
                toast.remove();
            }, 320);
        }, 3000);
    });

    const tabButtons = document.querySelectorAll('.settings-tab-btn');
    const tabPanels = document.querySelectorAll('.settings-panel');

    const activateTab = function (tabName) {
        tabButtons.forEach(function (button) {
            button.classList.toggle('active', button.dataset.tabTarget === tabName);
        });

        tabPanels.forEach(function (panel) {
            const isActive = panel.dataset.tabPanel === tabName;
            panel.classList.toggle('active', isActive);
        });
    };

    tabButtons.forEach(function (button) {
        button.addEventListener('click', function () {
            activateTab(button.dataset.tabTarget);
        });
    });

    const themeOptions = document.querySelectorAll('.theme-option');
    const storedTheme = localStorage.getItem('taskflow_theme') || 'system';

    const applyThemeSelection = function (value) {
        themeOptions.forEach(function (option) {
            const selected = option.dataset.themeValue === value;
            option.classList.toggle('selected', selected);
            const input = option.querySelector('input[type="radio"]');
            if (input) {
                input.checked = selected;
            }
        });
        document.documentElement.dataset.theme = value;
        localStorage.setItem('taskflow_theme', value);
    };

    themeOptions.forEach(function (option) {
        option.addEventListener('click', function () {
            applyThemeSelection(option.dataset.themeValue);
        });
    });

    applyThemeSelection(storedTheme);
});
