/* Éléments partagés entre toutes les pages du site de supervision :
 * dictionnaire de traduction FR/EN, bandeau de navigation, et fenêtres
 * popup personnalisées (remplacent alert()/confirm() natifs du navigateur).
 *
 * Chargé par dashboard.html, cell_detail.html, maintenance_history.html,
 * fault_history.html et data_comparison.html. Chaque page garde son propre
 * script pour sa logique spécifique (fetch des données, rendu des cartes,
 * etc.) et appelle les fonctions ci-dessous pour tout ce qui est commun.
 */

const NAV_I18N = {
    fr: {
        navMenu: "Menu",
        navMainView: "Vue principale",
        navMaintHistory: "Historique Maintenance",
        navFaultHistory: "Historique Pannes",
        navData: "Données",
        navBackDashboard: "← Retour au dashboard",
        navSignOut: "Déconnexion",
        modalClose: "Fermer",
        modalErrorTitle: "Erreur",
        modalSuccessTitle: "Succès",
        modalInfoTitle: "Information",
        accessDeniedTitle: "Accès réservé",
        accessDeniedBody: "Cette page est réservée au rôle MAINTENANCE.",
        accessDeniedBack: "Retour au dashboard",
    },
    en: {
        navMenu: "Menu",
        navMainView: "Main view",
        navMaintHistory: "Maintenance History",
        navFaultHistory: "Fault History",
        navData: "Data",
        navBackDashboard: "← Back to dashboard",
        navSignOut: "Sign Out",
        modalClose: "Close",
        modalErrorTitle: "Error",
        modalSuccessTitle: "Success",
        modalInfoTitle: "Information",
        accessDeniedTitle: "Restricted access",
        accessDeniedBody: "This page is restricted to the MAINTENANCE role.",
        accessDeniedBack: "Back to dashboard",
    },
};

function navLang() {
    return localStorage.getItem('src_lang') || 'fr';
}

function navT(key, dict) {
    const lang = navLang();
    const merged = { ...NAV_I18N[lang], ...(dict && dict[lang] ? dict[lang] : {}) };
    return merged[key] ?? NAV_I18N.fr[key] ?? key;
}

/**
 * Injecte le bandeau de navigation dans #topnav-root.
 * activePage: 'main' | 'maint-history' | 'fault-history' | 'data' | 'cell'
 * role: rôle courant ('OPERATEUR' | 'MAINTENANCE' | null)
 */
function renderTopNav(activePage, role) {
    const root = document.getElementById('topnav-root');
    if (!root) return;

    const isMaint = role === 'MAINTENANCE';
    const link = (page, href, label) => {
        const activeClass = activePage === page ? ' class="active"' : '';
        return `<a href="${href}"${activeClass}>${label}</a>`;
    };

    const links = [link('main', '/', navT('navMainView'))];
    if (isMaint) {
        links.push(link('maint-history', '/historique-maintenance', navT('navMaintHistory')));
        links.push(link('fault-history', '/historique-pannes', navT('navFaultHistory')));
        links.push(link('data', '/donnees', navT('navData')));
    }

    const roleLabel = role ? role : '---';

    root.innerHTML = `
        <header class="topnav">
            <div class="topnav-brand">
                <span class="dot-live"></span>
                Smart Robotic Cell — Supervision
            </div>
            <div class="topnav-right">
                <span class="topnav-badge role">${roleLabel}</span>
                <div class="topnav-menu">
                    <button class="topnav-menu-toggle" onclick="toggleNavDropdown()">
                        ${navT('navMenu')} ▾
                    </button>
                    <div class="topnav-dropdown" id="nav-dropdown">
                        ${links.join('')}
                    </div>
                </div>
                <button class="btn btn-nav" onclick="navSignOut()">${navT('navSignOut')}</button>
            </div>
        </header>
    `;
}

function toggleNavDropdown() {
    const dropdown = document.getElementById('nav-dropdown');
    if (!dropdown) return;
    dropdown.classList.toggle('open');
}

document.addEventListener('click', (evt) => {
    const dropdown = document.getElementById('nav-dropdown');
    const toggle = evt.target.closest('.topnav-menu-toggle');
    if (!dropdown || toggle) return;
    if (!evt.target.closest('.topnav-menu')) {
        dropdown.classList.remove('open');
    }
});

function navSignOut() {
    localStorage.removeItem('jwt_token');
    localStorage.removeItem('user_role');
    window.location.href = '/';
}

/* ---------- Fenêtre popup personnalisée (remplace alert()) ---------- */

function ensureModalRoot() {
    let overlay = document.getElementById('app-modal-overlay');
    if (overlay) return overlay;

    overlay = document.createElement('div');
    overlay.id = 'app-modal-overlay';
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
        <div class="modal-box">
            <div class="modal-header" id="app-modal-header"></div>
            <div class="modal-body" id="app-modal-body"></div>
            <div class="modal-footer">
                <button class="btn" id="app-modal-close-btn" onclick="closeModal()"></button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);
    overlay.addEventListener('click', (evt) => {
        if (evt.target === overlay) closeModal();
    });
    return overlay;
}

/**
 * Affiche une popup stylée à la place d'un alert() natif du navigateur.
 * type: 'info' | 'error' | 'success'
 */
function showModal(message, type = 'info', title = null) {
    const overlay = ensureModalRoot();
    const header = document.getElementById('app-modal-header');
    const body = document.getElementById('app-modal-body');
    const closeBtn = document.getElementById('app-modal-close-btn');

    const titleKey = type === 'error' ? 'modalErrorTitle'
        : type === 'success' ? 'modalSuccessTitle' : 'modalInfoTitle';

    header.className = `modal-header type-${type}`;
    header.innerText = title || navT(titleKey);
    body.innerText = message;
    closeBtn.innerText = navT('modalClose');

    overlay.classList.add('open');
}

function closeModal() {
    const overlay = document.getElementById('app-modal-overlay');
    if (overlay) overlay.classList.remove('open');
}

document.addEventListener('keydown', (evt) => {
    if (evt.key === 'Escape') closeModal();
});
