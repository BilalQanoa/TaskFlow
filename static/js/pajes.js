document.addEventListener('DOMContentLoaded', function () {
    const header = document.querySelector('.site-header');
    const navLinks = document.querySelectorAll('.nav-links a');
    const sections = document.querySelectorAll('section[id]');

    const toggleHeaderStyle = () => {
        if (window.scrollY > 24) {
            header.classList.add('scrolled');
        } else {
            header.classList.remove('scrolled');
        }
    };

    const setActiveLink = () => {
        const offset = window.innerHeight * 0.25;
        let activeSectionId = '';

        sections.forEach(section => {
            const rect = section.getBoundingClientRect();
            if (rect.top <= offset && rect.bottom > offset) {
                activeSectionId = section.id;
            }
        });

        navLinks.forEach(link => {
            const targetId = link.getAttribute('href').replace('#', '');
            if (targetId === activeSectionId) {
                link.classList.add('active');
            } else {
                link.classList.remove('active');
            }
        });
    };

    const smoothScroll = (event) => {
        const targetId = event.currentTarget.getAttribute('href').replace('#', '');
        const targetSection = document.getElementById(targetId);
        if (!targetSection) return;

        event.preventDefault();
        window.scrollTo({
            top: targetSection.offsetTop - header.offsetHeight - 12,
            behavior: 'smooth'
        });
    };

    window.addEventListener('scroll', () => {
        toggleHeaderStyle();
        setActiveLink();
    });

    navLinks.forEach(link => {
        link.addEventListener('click', smoothScroll);
    });

    toggleHeaderStyle();
    setActiveLink();
    document.body.classList.add('page-ready');
});