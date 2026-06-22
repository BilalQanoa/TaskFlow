document.addEventListener('DOMContentLoaded', function () {
    const kanbanBoard = document.getElementById('kanbanBoard');
    if (!kanbanBoard) return;

    const moveForm = document.getElementById('moveCardForm');
    const moveStatusInput = document.getElementById('moveCardStatus');

    // Add Card Modal Logic
    const modal = document.getElementById('addCardModal');
    const backdrop = document.getElementById('addCardBackdrop');
    const statusInput = document.getElementById('addCardStatus');
    const columnLabel = document.getElementById('addCardColumnLabel');

    const columnLabels = {
        todo: 'To Do',
        in_progress: 'In Progress',
        under_review: 'Under Review',
        done: 'Done',
    };

    function openAddCardModal(status) {
        if (!modal || !backdrop) return;
        statusInput.value = status;
        columnLabel.textContent = columnLabels[status] || status;
        modal.classList.add('show');
        backdrop.classList.add('show');
        modal.setAttribute('aria-hidden', 'false');
        backdrop.setAttribute('aria-hidden', 'false');
        document.body.classList.add('modal-open');
        const titleInput = document.getElementById('add_card_title');
        if (titleInput) titleInput.focus();
    }

    function closeAddCardModal() {
        if (!modal || !backdrop) return;
        modal.classList.remove('show');
        backdrop.classList.remove('show');
        modal.setAttribute('aria-hidden', 'true');
        backdrop.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('modal-open');
    }

    document.querySelectorAll('.tl-add-card-btn').forEach(function (button) {
        button.addEventListener('click', function () {
            openAddCardModal(button.dataset.addStatus);
        });
    });

    document.querySelectorAll('[data-close-add-card]').forEach(function (button) {
        button.addEventListener('click', closeAddCardModal);
    });

    if (backdrop) {
        backdrop.addEventListener('click', closeAddCardModal);
    }

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && modal && modal.classList.contains('show')) {
            closeAddCardModal();
        }
    });

    let draggedCard = null;
    const BLOCKED_COLUMNS = ['done'];

    document.querySelectorAll('.tl-trello-card--draggable').forEach(function (card) {
        card.addEventListener('dragstart', function (event) {
            draggedCard = card;
            card.classList.add('tl-trello-card--dragging');
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', card.dataset.cardId);
        });

        card.addEventListener('dragend', function () {
            card.classList.remove('tl-trello-card--dragging');
            draggedCard = null;
            document.querySelectorAll('.tl-trello-cards--drag-over').forEach(function (zone) {
                zone.classList.remove('tl-trello-cards--drag-over');
            });
        });
    });

    document.querySelectorAll('.tl-trello-cards--droppable').forEach(function (dropZone) {
        dropZone.addEventListener('dragover', function (event) {
            const newStatus = dropZone.dataset.dropStatus;
            if (BLOCKED_COLUMNS.includes(newStatus)) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = 'move';
            dropZone.classList.add('tl-trello-cards--drag-over');
        });

        dropZone.addEventListener('dragleave', function () {
            dropZone.classList.remove('tl-trello-cards--drag-over');
        });

        dropZone.addEventListener('drop', function (event) {
            const newStatus = dropZone.dataset.dropStatus;
            if (BLOCKED_COLUMNS.includes(newStatus)) return;
            event.preventDefault();
            dropZone.classList.remove('tl-trello-cards--drag-over');
            if (!draggedCard || !moveForm) return;

            const cardId = draggedCard.dataset.cardId;
            const currentColumn = draggedCard.closest('.tl-trello-column');
            const currentStatus = currentColumn ? currentColumn.dataset.status : '';

            if (!cardId || !newStatus || newStatus === currentStatus) return;

            const moveBase = moveForm.dataset.moveBase || '';
            moveForm.action = moveBase.replace('/0/', '/' + cardId + '/');
            moveStatusInput.value = newStatus;
            moveForm.submit();
        });
    });
});
