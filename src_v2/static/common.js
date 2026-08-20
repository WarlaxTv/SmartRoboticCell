/* Éléments partagés entre toutes les pages du site de supervision :
 * dictionnaire de traduction FR/EN, bandeau de navigation, et fenêtres
 * popup personnalisées (remplacent alert()/confirm() natifs du navigateur).
 *
 * Chargé par dashboard.html, cell_detail.html, maintenance_history.html,
 * fault_history.html et data_comparison.html. Chaque page garde son propre
 * script pour sa logique spécifique (fetch des données, rendu des cartes,
 * etc.) et appelle les fonctions ci-dessous pour tout ce qui est commun.
 */

/* Noms des 3 cellules, tels qu'exposés par le serveur OPC UA simulé
 * (src_v2/opcua_server.py, variable cell_names) : fixes pour ce POC à 3
 * cellules. Dupliqués ici (plutôt que récupérés via /api/status) pour que
 * les pages d'historique (fault_history.html, maintenance_history.html)
 * puissent afficher un menu de filtre lisible sans dépendre d'un appel API
 * supplémentaire ni d'un rôle OPERATEUR/MAINTENANCE particulier. */
const CELL_NAMES = {
    1: "PERÇAGE AÉRO",
    2: "ASSEMBLAGE",
    3: "CONTRÔLE QUALITÉ",
};

function cellDisplayName(cellId) {
    const name = CELL_NAMES[cellId];
    return name ? `#${cellId} — ${name}` : `#${cellId}`;
}

/* Statut d'un DefautHistorique (voir src_v2/db.py) : "actif" (pas encore
 * pris en charge, = demande d'intervention implicite), "en_cours" (une
 * intervention a eu lieu mais le problème persiste) ou "resolu". */
const FAULT_STATUS_TAG_CLASS = {
    actif: "unresolved-tag",
    en_cours: "status-en-cours-tag",
    resolu: "resolved-tag",
};

function faultStatusTagClass(status) {
    return FAULT_STATUS_TAG_CLASS[status] || "unresolved-tag";
}

/* Traduction FR→EN des libellés de défauts (type_defaut/description, voir
 * src_v2/db.py::DefautHistorique). Contrairement à l'historique de
 * maintenance (action librement composée, notes libres saisies par un
 * utilisateur — jamais retraduites, cf. CHG-V2-057), le vocabulaire des
 * défauts est fermé et connu à l'avance : il vient uniquement du catalogue
 * de démonstration (scripts/seed_historical_data.py::FAULT_TYPES) ou du
 * panneau de simulation (web_server.py::FAULT_TYPE_MANUAL). Un texte qui ne
 * correspond à aucune entrée connue est renvoyé inchangé (pas de perte de
 * données si le catalogue évolue sans que cette liste soit mise à jour).
 * Tableau (et non objet) pour préserver l'ordre d'application : les phrases
 * complètes doivent être remplacées avant le mot générique "Cellule". */
const FAULT_TEXT_FR_TO_EN = [
    ["Défaut capteur température", "Temperature sensor fault"],
    ["Surcharge moteur (courant élevé)", "Motor overload (high current)"],
    ["Perte de communication OPC UA", "OPC UA communication loss"],
    ["Pression pneumatique hors tolérance", "Pneumatic pressure out of tolerance"],
    ["Niveau lubrifiant bas", "Low lubricant level"],
    ["Collision détectée (arrêt d'urgence)", "Collision detected (emergency stop)"],
    ["Dérive de trajectoire (recalibrage requis)", "Trajectory drift (recalibration required)"],
    ["Défaut préhenseur / pince", "Gripper fault"],
    ["Défaut déclenché manuellement (simulation)", "Fault manually triggered (simulation)"],
    ["Défaut forcé depuis le panneau de simulation (POC).", "Fault forced from the simulation panel (POC)."],
    ["(jeu de données historique)", "(historical demo dataset)"],
    ["Cellule", "Cell"],
];

function translateFaultText(text) {
    if (navLang() !== 'en' || !text) return text;
    let result = text;
    for (const [fr, en] of FAULT_TEXT_FR_TO_EN) {
        result = result.split(fr).join(en);
    }
    return result;
}

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
        promptSubmit: "Envoyer",
        promptCancel: "Annuler",
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
        promptSubmit: "Send",
        promptCancel: "Cancel",
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
    const langLabel = navLang() === 'fr' ? 'EN' : 'FR';

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
                <button class="btn btn-nav" onclick="toggleNavLanguage()">${langLabel}</button>
                <button class="btn btn-nav" onclick="navSignOut()">${navT('navSignOut')}</button>
            </div>
        </header>
    `;
}

/**
 * Bascule la langue (FR/EN) et recharge la page.
 *
 * Le bandeau de navigation est partagé par toutes les pages (dashboard,
 * détail cellule, historiques, comparaison de données), mais chacune gère
 * son propre contenu dynamique (listes rafraîchies par polling, graphiques
 * Chart.js, etc.). Plutôt que d'exiger de chaque page qu'elle expose un hook
 * de retraduction cohérent pour tout son contenu déjà affiché, on recharge la
 * page : chaque page relit déjà systématiquement la langue stockée
 * (localStorage) à son chargement, donc un rechargement suffit à tout
 * réafficher dans la langue choisie, sans risque d'oubli ponctuel.
 */
function toggleNavLanguage() {
    const next = navLang() === 'fr' ? 'en' : 'fr';
    localStorage.setItem('src_lang', next);
    window.location.reload();
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
    if (evt.key === 'Escape') {
        closeModal();
        closeTextPromptModal();
    }
});

/* ---------- Fenêtre de saisie de texte libre (remplace prompt()) ---------- */

let _textPromptCallback = null;

function ensureTextPromptRoot() {
    let overlay = document.getElementById('app-textprompt-overlay');
    if (overlay) return overlay;

    overlay = document.createElement('div');
    overlay.id = 'app-textprompt-overlay';
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
        <div class="modal-box">
            <div class="modal-header" id="app-textprompt-header"></div>
            <div class="modal-body">
                <div class="form-field">
                    <textarea id="app-textprompt-input" rows="3"></textarea>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-reset" id="app-textprompt-cancel-btn" onclick="closeTextPromptModal()"></button>
                <button class="btn" id="app-textprompt-submit-btn" onclick="submitTextPromptModal()"></button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);
    overlay.addEventListener('click', (evt) => {
        if (evt.target === overlay) closeTextPromptModal();
    });
    return overlay;
}

/**
 * Affiche une popup de saisie de texte libre, à la place d'un prompt()
 * natif du navigateur. ``callback(text)`` n'est appelé QUE si
 * l'utilisateur clique "Envoyer" (texte éventuellement vide) ; un clic sur
 * "Annuler", en dehors de la popup, ou Échap ferme sans rien appeler.
 */
function openTextPromptModal(title, placeholder, callback) {
    const overlay = ensureTextPromptRoot();
    document.getElementById('app-textprompt-header').innerText = title;
    const input = document.getElementById('app-textprompt-input');
    input.value = '';
    input.placeholder = placeholder || '';
    document.getElementById('app-textprompt-cancel-btn').innerText = navT('promptCancel');
    document.getElementById('app-textprompt-submit-btn').innerText = navT('promptSubmit');
    _textPromptCallback = callback;
    overlay.classList.add('open');
    input.focus();
}

function closeTextPromptModal() {
    const overlay = document.getElementById('app-textprompt-overlay');
    if (overlay) overlay.classList.remove('open');
    _textPromptCallback = null;
}

function submitTextPromptModal() {
    const input = document.getElementById('app-textprompt-input');
    const value = input ? input.value.trim() : '';
    const callback = _textPromptCallback;
    closeTextPromptModal();
    if (callback) callback(value);
}

/* ---------- Agrandissement d'un graphique Chart.js ---------- */

function ensureChartZoomRoot() {
    let overlay = document.getElementById('chart-zoom-overlay');
    if (overlay) return overlay;

    overlay = document.createElement('div');
    overlay.id = 'chart-zoom-overlay';
    overlay.className = 'chart-zoom-overlay';
    overlay.innerHTML = `
        <div class="chart-zoom-box">
            <div class="chart-zoom-header">
                <span id="chart-zoom-title"></span>
                <button class="btn" onclick="closeChartZoom()">&times;</button>
            </div>
            <div class="chart-zoom-body"><canvas id="chart-zoom-canvas"></canvas></div>
        </div>
    `;
    document.body.appendChild(overlay);
    overlay.addEventListener('click', (evt) => {
        if (evt.target === overlay) closeChartZoom();
    });
    return overlay;
}

let chartZoomInstance = null;

/**
 * Ouvre une version agrandie d'un graphique Chart.js existant (nouvelle
 * fenêtre modale plein écran). Chart.js ne permet pas de déplacer une
 * instance existante vers un autre <canvas> : on reconstruit un nouveau
 * graphique avec les mêmes jeux de données/options sur un plus grand canvas.
 */
function openChartZoom(title, datasets, options) {
    const overlay = ensureChartZoomRoot();
    document.getElementById('chart-zoom-title').innerText = title;
    if (chartZoomInstance) chartZoomInstance.destroy();
    const ctx = document.getElementById('chart-zoom-canvas');
    chartZoomInstance = new Chart(ctx, {
        type: 'line',
        data: { datasets },
        options: options || {},
    });
    overlay.classList.add('open');
}

function closeChartZoom() {
    const overlay = document.getElementById('chart-zoom-overlay');
    if (overlay) overlay.classList.remove('open');
    if (chartZoomInstance) {
        chartZoomInstance.destroy();
        chartZoomInstance = null;
    }
}

document.addEventListener('keydown', (evt) => {
    if (evt.key === 'Escape') closeChartZoom();
});
