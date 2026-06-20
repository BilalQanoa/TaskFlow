document.addEventListener('DOMContentLoaded', function () {
    const createModal = document.getElementById('createTeamModal');
    if (createModal) {
        const openButtons = document.querySelectorAll('.open-create-team-modal');
        const closeButtons = createModal.querySelectorAll('[data-close-modal]');

        const openCreateModal = function () {
            createModal.classList.add('active');
            createModal.setAttribute('aria-hidden', 'false');
            const firstInput = createModal.querySelector('input');
            if (firstInput) {
                firstInput.focus();
            }
        };

        const closeCreateModal = function () {
            createModal.classList.remove('active');
            createModal.setAttribute('aria-hidden', 'true');
        };

        openButtons.forEach(function (button) {
            button.addEventListener('click', openCreateModal);
        });

        closeButtons.forEach(function (button) {
            button.addEventListener('click', closeCreateModal);
        });

        createModal.addEventListener('click', function (event) {
            if (event.target === createModal) {
                closeCreateModal();
            }
        });

        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && createModal.classList.contains('active')) {
                closeCreateModal();
            }
        });
    }

    const deleteModal = document.getElementById('deleteTeamModal');
    if (!deleteModal) {
        return;
    }

    const openDeleteButtons = document.querySelectorAll('.delete-team-trigger');
    const closeDeleteButtons = deleteModal.querySelectorAll('[data-close-delete-modal]');

    const openDeleteModal = function () {
        deleteModal.classList.add('active');
        deleteModal.setAttribute('aria-hidden', 'false');
    };

    const closeDeleteModal = function () {
        deleteModal.classList.remove('active');
        deleteModal.setAttribute('aria-hidden', 'true');
    };

    openDeleteButtons.forEach(function (button) {
        button.addEventListener('click', openDeleteModal);
    });

    closeDeleteButtons.forEach(function (button) {
        button.addEventListener('click', closeDeleteModal);
    });

    deleteModal.addEventListener('click', function (event) {
        if (event.target === deleteModal) {
            closeDeleteModal();
        }
    });

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && deleteModal.classList.contains('active')) {
            closeDeleteModal();
        }
    });
});
