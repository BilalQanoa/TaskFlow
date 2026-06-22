document.addEventListener('DOMContentLoaded', function () {
    if (typeof $ !== 'undefined' && $.fn.select2) {
        $('.searchable-select').select2({
            placeholder: 'Search teammate by name or title...',
            allowClear: true,
            width: '100%'
        });
    }
});
