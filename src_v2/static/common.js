/* Éléments partagés entre toutes les pages du site de supervision :
 * dictionnaire de traduction FR/EN, bandeau de navigation, et fenêtres
 * popup personnalisées (remplacent alert()/confirm() natifs du navigateur).
 *
 * Chargé par dashboard.html, cell_detail.html, maintenance_history.html,
 * fault_history.html et data_comparison.html. Chaque page garde son propre
 * script pour sa logique spécifique (fetch des données, rendu des cartes,
 * etc.) et appelle les fonctions ci-dessous pour tout ce qui est commun.
 */

/* Identité des cellules (nom par id, liste complète) : gérée dynamiquement
 * depuis la base (table Cellule) plutôt que codée en dur ici, depuis que
 * l'Administrateur peut créer de nouvelles cellules (cf. CHG-V2-088) — ce
 * POC ne se limite plus à 3 cellules fixes. CELL_NAMES/CELL_LIST démarrent
 * vides et sont peuplés par loadCellNames() ci-dessous ; en attendant ce
 * chargement, cellDisplayName() retombe sur "#<id>" plutôt que de planter. */
let CELL_NAMES = {};
let CELL_LIST = []; // [{id, nom}, ...] tel que renvoyé par GET /api/cells

function cellDisplayName(cellId) {
    const name = CELL_NAMES[cellId];
    return name ? `#${cellId} — ${name}` : `#${cellId}`;
}

/**
 * Charge la liste des cellules existantes (GET /api/cells, ouvert à tout
 * rôle authentifié) et peuple CELL_NAMES/CELL_LIST. Chaque page doit
 * `await loadCellNames()` avant tout rendu dépendant de cellDisplayName()
 * ou de la liste des cellules (menus de filtre de fault_history.html/
 * maintenance_history.html, sections par cellule de data_comparison.html).
 * Remplace l'ancienne constante CELL_NAMES figée à 3 entrées codées en dur.
 */
async function loadCellNames() {
    const token = localStorage.getItem('jwt_token');
    if (!token) return;
    try {
        const resp = await fetch('/api/cells', {
            headers: { Authorization: `Bearer ${token}` },
        });
        if (!resp.ok) return;
        const data = await resp.json();
        CELL_LIST = data.cells || [];
        CELL_NAMES = {};
        for (const c of CELL_LIST) CELL_NAMES[c.id] = c.nom;
    } catch (e) {
        console.error(e);
    }
}

/**
 * ADMIN a tous les droits (cf. décision utilisateur : "Admin = tous les
 * droits"), y compris ceux normalement réservés à MAINTENANCE. Centralise
 * cette vérification plutôt que de dupliquer `role === 'MAINTENANCE' ||
 * role === 'ADMIN'` à chaque site d'appel de chaque page.
 */
function hasMaintenanceRights(role) {
    return role === 'MAINTENANCE' || role === 'ADMIN';
}

/**
 * Pages/actions en lecture ouvertes à la fois à Maintenance et Opérateur
 * (cf. décision utilisateur round 6) : ADMIN y a accès aussi, cohérent avec
 * hasMaintenanceRights() ci-dessus.
 */
function hasPageAccess(role) {
    return role === 'MAINTENANCE' || role === 'OPERATEUR' || role === 'ADMIN';
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
    ["Anomalie signalée par la Maintenance", "Issue reported by Maintenance"],
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
        navAdmin: "Administration",
        navBackDashboard: "← Retour au dashboard",
        navSignOut: "Déconnexion",
        modalClose: "Fermer",
        modalErrorTitle: "Erreur",
        modalSuccessTitle: "Succès",
        modalInfoTitle: "Information",
        promptSubmit: "Envoyer",
        promptCancel: "Annuler",
        confirmOk: "Confirmer",
        accessDeniedTitle: "Accès réservé",
        accessDeniedBody: "Cette page est réservée au rôle MAINTENANCE.",
        accessDeniedBodyAdmin: "Cette page est réservée au rôle ADMIN.",
        accessDeniedBack: "Retour au dashboard",
    },
    en: {
        navMenu: "Menu",
        navMainView: "Main view",
        navMaintHistory: "Maintenance History",
        navFaultHistory: "Fault History",
        navData: "Data",
        navAdmin: "Administration",
        navBackDashboard: "← Back to dashboard",
        navSignOut: "Sign Out",
        modalClose: "Close",
        modalErrorTitle: "Error",
        modalSuccessTitle: "Success",
        modalInfoTitle: "Information",
        promptSubmit: "Send",
        promptCancel: "Cancel",
        confirmOk: "Confirm",
        accessDeniedTitle: "Restricted access",
        accessDeniedBody: "This page is restricted to the MAINTENANCE role.",
        accessDeniedBodyAdmin: "This page is restricted to the ADMIN role.",
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
    const isOperator = role === 'OPERATEUR';
    const isAdmin = role === 'ADMIN';
    const link = (page, href, label) => {
        const activeClass = activePage === page ? ' class="active"' : '';
        return `<a href="${href}"${activeClass}>${label}</a>`;
    };

    const links = [link('main', '/', navT('navMainView'))];
    // Historique maintenance/défauts : accessible en lecture à l'Opérateur
    // aussi (ses propres demandes + tous les défauts, cf. CHG-V2-066).
    // Données (courbes de comparaison) ouvert en lecture à l'Opérateur
    // également (cf. décision utilisateur round 6 : "la seule chose que
    // l'opérateur ne peut pas faire c'est créer des alertes, ni télécharger
    // les graphs" — l'onglet Courbes reste donc visible, seul le
    // téléchargement (CSV/image) est réservé à la Maintenance, cf.
    // data_comparison.html). ADMIN a tous les droits (cf.
    // hasMaintenanceRights ci-dessus) : accès aux mêmes pages que la
    // Maintenance, plus le lien Administration ci-dessous.
    if (isMaint || isOperator || isAdmin) {
        links.push(link('maint-history', '/historique-maintenance', navT('navMaintHistory')));
        links.push(link('fault-history', '/historique-pannes', navT('navFaultHistory')));
        links.push(link('data', '/donnees', navT('navData')));
    }
    // Gestion des comptes et des cellules : réservée à ADMIN (cf. demande
    // utilisateur "compte administrateur ... créer des comptes ... créer
    // des nouvelles cellules de robots").
    if (isAdmin) {
        links.push(link('admin', '/administration', navT('navAdmin')));
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
        closeConfirmModal();
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

/* ---------- Fenêtre de confirmation (remplace confirm()) ---------- */

let _confirmCallback = null;

function ensureConfirmRoot() {
    let overlay = document.getElementById('app-confirm-overlay');
    if (overlay) return overlay;

    overlay = document.createElement('div');
    overlay.id = 'app-confirm-overlay';
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
        <div class="modal-box">
            <div class="modal-header" id="app-confirm-header"></div>
            <div class="modal-body" id="app-confirm-body"></div>
            <div class="modal-footer">
                <button class="btn btn-reset" id="app-confirm-cancel-btn" onclick="closeConfirmModal()"></button>
                <button class="btn" id="app-confirm-ok-btn" onclick="submitConfirmModal()"></button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);
    overlay.addEventListener('click', (evt) => {
        if (evt.target === overlay) closeConfirmModal();
    });
    return overlay;
}

/**
 * Affiche une popup de confirmation oui/non, à la place d'un confirm()
 * natif du navigateur. ``callback()`` n'est appelé QUE si l'utilisateur
 * clique le bouton de confirmation ; un clic sur "Annuler", en dehors de la
 * popup, ou Échap ferme sans rien appeler. Utilisé pour les actions
 * destructives (ex. suppression d'une cellule depuis /administration).
 */
function openConfirmModal(title, message, callback) {
    const overlay = ensureConfirmRoot();
    document.getElementById('app-confirm-header').innerText = title;
    document.getElementById('app-confirm-body').innerText = message;
    document.getElementById('app-confirm-cancel-btn').innerText = navT('promptCancel');
    document.getElementById('app-confirm-ok-btn').innerText = navT('confirmOk');
    _confirmCallback = callback;
    overlay.classList.add('open');
}

function closeConfirmModal() {
    const overlay = document.getElementById('app-confirm-overlay');
    if (overlay) overlay.classList.remove('open');
    _confirmCallback = null;
}

function submitConfirmModal() {
    const callback = _confirmCallback;
    closeConfirmModal();
    if (callback) callback();
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
 *
 * ``labels`` est optionnel : à fournir explicitement quand l'appelant a dû
 * fusionner/trier lui-même les horodatages de plusieurs séries (cf.
 * data_comparison.html et INC-V2-021) — sans quoi la version agrandie
 * réintroduirait les mêmes sauts en arrière que le graphique d'origine.
 * Omis (undefined), Chart.js retrouve son comportement par défaut
 * (extraction des catégories depuis le champ "x" de chaque point), utilisé
 * par cell_detail.html où une seule série par axe suffit.
 */
function openChartZoom(title, datasets, options, labels) {
    const overlay = ensureChartZoomRoot();
    document.getElementById('chart-zoom-title').innerText = title;
    if (chartZoomInstance) chartZoomInstance.destroy();
    const ctx = document.getElementById('chart-zoom-canvas');
    const data = labels ? { labels, datasets } : { datasets };
    chartZoomInstance = new Chart(ctx, {
        type: 'line',
        data,
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

/**
 * Télécharge une image PNG d'un graphique Chart.js (cf. demande utilisateur
 * round 6 : "pour les courbes j'aimerais que l'on puisse télécharger une
 * image de la courbe"). Réutilisé par cell_detail.html et
 * data_comparison.html. Réservé au rôle MAINTENANCE côté appelant (comme le
 * reste des téléchargements) : "la seule chose que l'opérateur ne peut pas
 * faire c'est créer des alertes, ni télécharger les graphs".
 */
function downloadChartAsImage(chart, filename) {
    if (!chart) return;
    // Fond blanc explicite : Chart.js dessine sur un canvas transparent par
    // défaut, ce qui produirait un PNG illisible une fois collé dans un
    // document ou imprimé sur fond blanc (les courbes/labels sombres se
    // fondent). On compose donc l'image du graphique sur un canvas
    // intermédiaire rempli de blanc avant export.
    const sourceCanvas = chart.canvas;
    const composite = document.createElement('canvas');
    composite.width = sourceCanvas.width;
    composite.height = sourceCanvas.height;
    const ctx = composite.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, composite.width, composite.height);
    ctx.drawImage(sourceCanvas, 0, 0);
    const url = composite.toDataURL('image/png');
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

/**
 * Fusionne les horodatages de plusieurs séries temporelles (`.time` sur
 * chaque élément) en une liste triée et dédupliquée, à fournir explicitement
 * comme "labels" d'un graphique Chart.js à plusieurs jeux de données dont
 * les horodatages ne coïncident pas exactement d'une série à l'autre.
 *
 * Sans cette fusion, l'axe X de type "category" de Chart.js construit sa
 * propre liste de catégories en concaténant les horodatages dans l'ordre où
 * il rencontre chaque nouveau jeu de données : un horodatage propre à une
 * série tardive, absent des séries précédentes, est alors ajouté en FIN de
 * liste plutôt qu'à sa place chronologique, ce qui fait bondir en arrière le
 * tracé de cette série (cf. INC-V2-021 sur data_comparison.html — 3
 * cellules échantillonnées l'une après l'autre dans la même itération de la
 * boucle de fond, donc décalées de quelques secondes ; et CHG-V2-086 sur
 * cell_detail.html — 6 axes écrits en base par des INSERT distincts au même
 * tick, occasionnellement décalés d'1s d'un axe à l'autre, un écart qui
 * n'apparaissait pas avant l'introduction du moyennage par paquets de
 * `decimateSeries` ci-dessous).
 */
function mergedSortedTimes(timedArrays) {
    const seen = new Set();
    for (const arr of timedArrays) {
        for (const item of arr) seen.add(item.time);
    }
    return Array.from(seen).sort();
}

/**
 * Télécharge l'image PNG d'une courbe dans sa taille/mise en forme AGRANDIE
 * (mêmes options qu'`openChartZoom`), pas la petite vignette en ligne :
 * signalé par l'utilisateur ("quand on télécharge l'image il faut que ce
 * soit l'image de quand on agrandit la courbe"). Construit un graphique
 * Chart.js temporaire sur un canvas hors écran aux dimensions de la fenêtre
 * agrandie, télécharge son image, puis le détruit — sans jamais ouvrir la
 * modale d'agrandissement à l'écran.
 */
function downloadZoomedChartImage(datasets, options, labels, filename) {
    const canvas = document.createElement('canvas');
    // Mêmes proportions que la fenêtre modale d'agrandissement (cf.
    // .chart-zoom-box dans theme.css), en résolution native pour un export
    // net plutôt qu'une capture basse résolution de la vignette d'origine.
    canvas.width = 1600;
    canvas.height = 800;
    const offscreenOptions = { ...options, responsive: false, animation: false };
    const data = labels ? { labels, datasets } : { datasets };
    const chart = new Chart(canvas, { type: 'line', data, options: offscreenOptions });
    downloadChartAsImage(chart, filename);
    chart.destroy();
}

/**
 * Réduit une série temporelle triée (ascendant) à au plus `maxPoints`
 * points, en moyennant par paquets de points bruts consécutifs plutôt qu'en
 * en gardant un sur N au hasard — cf. problème signalé par l'utilisateur
 * ("toujours des problèmes avec des pics sur les données dans les courbes,
 * des points de courbes pas réguliers, et les traits sont pas lisibles").
 *
 * Deux causes distinctes derrière ce symptôme, corrigées ensemble par ce
 * moyennage : (1) sur une fenêtre de 24h/7j/30j, l'échantillonnage toutes
 * les 15s produit des milliers de points pour quelques centaines de pixels
 * de large, ce qui rend les courbes illisibles (traits qui se confondent en
 * une masse épaisse) ; (2) de rares redémarrages du serveur OPC UA
 * (`opcua_server.py`) réinitialisent momentanément les 6 axes à leur valeur
 * "idle" de départ pendant une seule mesure avant de remonter — un pic
 * vertical isolé et non représentatif. Moyenner sur des paquets de points
 * bruts dilue mécaniquement ce genre de valeur isolée (elle ne pèse plus que
 * 1/N dans la moyenne de son paquet) tout en régularisant l'espacement
 * visuel des points affichés.
 *
 * `points` : tableau d'objets triés par temps croissant. `timeField` : nom
 * du champ horodatage (conservé tel quel, pris au point médian du paquet).
 * `valueFields` : champs numériques à moyenner. Ne modifie pas `points`.
 */
function decimateSeries(points, timeField, valueFields, maxPoints) {
    if (!points || points.length <= maxPoints) return points || [];
    const bucketSize = Math.ceil(points.length / maxPoints);
    const result = [];
    for (let i = 0; i < points.length; i += bucketSize) {
        const chunk = points.slice(i, i + bucketSize);
        const bucket = {};
        for (const field of valueFields) {
            const values = chunk
                .map((p) => p[field])
                .filter((v) => v !== undefined && v !== null && !Number.isNaN(v));
            // Arrondi à 2 décimales : sans cela, la division en JS introduit
            // un bruit de dernière décimale binaire (ex. 6.2 devient
            // 6.200000000000001 sur certains paquets et reste 6.2 sur
            // d'autres) qui n'a aucun sens physique (aucun capteur simulé
            // n'a cette précision) et force l'échelle Y de Chart.js à
            // zoomer sur cet écart infinitésimal — symptôme observé par
            // l'utilisateur sur la courbe de pression pneumatique, dont la
            // valeur brute est pourtant parfaitement constante (6.2 bar).
            bucket[field] = values.length
                ? Math.round((values.reduce((a, b) => a + b, 0) / values.length) * 100) / 100
                : null;
        }
        bucket[timeField] = chunk[Math.floor(chunk.length / 2)][timeField];
        result.push(bucket);
    }
    return result;
}

/* ---------- Dates localisées (FR / EN) ----------
 *
 * Les horodatages renvoyés par l'API sont des chaînes "AAAA-MM-JJ HH:MM:SS"
 * (heure locale du serveur, cf. db.py). On les affiche selon la langue de
 * l'interface (bouton FR/EN du bandeau) :
 *   - FR : 11/09/2026 15:52:10        (jj/mm/aaaa, 24 h)
 *   - EN : 09/11/2026 3:52:10 PM      (mm/dd/yyyy, 12 h AM/PM)
 * Le découpage se fait sur la chaîne elle-même (pas de `new Date()`), pour
 * éviter tout décalage de fuseau horaire sur une heure déjà locale.
 * Pour changer le format anglais (ex. jj/mm/aaaa à l'anglaise), il suffit
 * de modifier DATE_FORMATS ci-dessous. */

const DATE_FORMATS = {
    fr: { order: ['d', 'm', 'y'], sep: '/', hour12: false, placeholder: 'jj/mm/aaaa' },
    en: { order: ['m', 'd', 'y'], sep: '/', hour12: true, placeholder: 'mm/dd/yyyy' },
};

function _dateFormat(lang) {
    return DATE_FORMATS[lang] || DATE_FORMATS.fr;
}

function _pad2(n) {
    return String(n).padStart(2, '0');
}

function parseDbTimestamp(value) {
    const m = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?/.exec(String(value ?? '').trim());
    if (!m) return null;
    return {
        y: Number(m[1]),
        mo: Number(m[2]),
        d: Number(m[3]),
        h: m[4] === undefined ? null : Number(m[4]),
        mi: m[5] === undefined ? 0 : Number(m[5]),
        s: m[6] === undefined ? 0 : Number(m[6]),
    };
}

function _formatDateParts(p, fmt) {
    const parts = { d: _pad2(p.d), m: _pad2(p.mo), y: String(p.y) };
    return fmt.order.map((k) => parts[k]).join(fmt.sep);
}

/** Date seule ("AAAA-MM-JJ" ou horodatage complet) au format de la langue. */
function formatDate(value, lang = navLang()) {
    const p = parseDbTimestamp(value);
    if (!p) return value === null || value === undefined ? '' : String(value);
    return _formatDateParts(p, _dateFormat(lang));
}

/** Date + heure au format de la langue ; valeur illisible renvoyée telle quelle. */
function formatDateTime(value, lang = navLang()) {
    const p = parseDbTimestamp(value);
    if (!p) return value === null || value === undefined ? '' : String(value);
    const fmt = _dateFormat(lang);
    const datePart = _formatDateParts(p, fmt);
    if (p.h === null) return datePart;
    if (!fmt.hour12) return `${datePart} ${_pad2(p.h)}:${_pad2(p.mi)}:${_pad2(p.s)}`;
    const suffix = p.h >= 12 ? 'PM' : 'AM';
    const h12 = p.h % 12 === 0 ? 12 : p.h % 12;
    return `${datePart} ${h12}:${_pad2(p.mi)}:${_pad2(p.s)} ${suffix}`;
}

/**
 * Lit une date saisie à la main dans la langue courante et la renvoie au
 * format ISO "AAAA-MM-JJ" (utilisé par l'API), ou null si elle est invalide
 * (ex. 31/02/2026). Accepte aussi l'ISO direct, et "/", "-", "." ou espace
 * comme séparateurs ; une année sur 2 chiffres est prise dans les années 2000.
 */
function parseLocalizedDate(text, lang = navLang()) {
    const raw = String(text ?? '').trim();
    if (!raw) return null;
    let y;
    let mo;
    let d;
    const iso = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/.exec(raw);
    if (iso) {
        [y, mo, d] = [Number(iso[1]), Number(iso[2]), Number(iso[3])];
    } else {
        const parts = raw.split(/[\/.\-\s]+/);
        if (parts.length !== 3 || parts.some((x) => !/^\d+$/.test(x))) return null;
        const byKey = {};
        _dateFormat(lang).order.forEach((k, i) => { byKey[k] = Number(parts[i]); });
        ({ y, m: mo, d } = byKey);
        if (parts[_dateFormat(lang).order.indexOf('y')].length <= 2) y += 2000;
    }
    const check = new Date(Date.UTC(y, mo - 1, d));
    if (
        Number.isNaN(check.getTime())
        || check.getUTCFullYear() !== y
        || check.getUTCMonth() !== mo - 1
        || check.getUTCDate() !== d
    ) return null;
    return `${String(y).padStart(4, '0')}-${_pad2(mo)}-${_pad2(d)}`;
}

/* ---------- Champ de date localisé (barres de filtre) ----------
 *
 * Un <input type="date"> natif s'affiche selon la langue du NAVIGATEUR, pas
 * celle de l'interface : passer le site en EN ne changeait donc rien au
 * format du filtre. Ce composant affiche un champ texte au format de la
 * langue de l'interface (jj/mm/aaaa ou mm/dd/yyyy) et garde le calendrier
 * natif accessible via un bouton. Structure attendue dans la page :
 *
 *   <div class="date-field">
 *       <input type="text" id="since-filter" class="filter-input date-text">
 *       <button type="button" class="date-picker-btn"></button>
 *       <input type="date" class="date-native" tabindex="-1" aria-hidden="true">
 *   </div>
 *
 * La valeur exploitable par l'API (ISO) se lit avec getDateFieldIso(id).
 */

const DATE_FIELD_I18N = {
    fr: { calendar: 'Ouvrir le calendrier', invalid: 'Date invalide — format attendu : ' },
    en: { calendar: 'Open calendar', invalid: 'Invalid date — expected format: ' },
};

function _dateFieldText(key) {
    const lang = navLang();
    return (DATE_FIELD_I18N[lang] || DATE_FIELD_I18N.fr)[key];
}

function getDateFieldIso(id) {
    const input = document.getElementById(id);
    return input ? (input.dataset.iso || '') : '';
}

function setDateFieldIso(id, iso) {
    const input = document.getElementById(id);
    if (!input) return;
    input.dataset.iso = iso || '';
    input.value = iso ? formatDate(iso) : '';
    input.classList.remove('invalid');
    input.removeAttribute('aria-invalid');
}

function resetDateField(id) {
    setDateFieldIso(id, '');
}

/** À appeler une fois par page, après le chargement du DOM. `onChange` est
 *  rappelé quand une date valide est saisie/choisie ou quand le champ est vidé. */
function initDateFields(onChange) {
    const fmt = _dateFormat(navLang());
    document.querySelectorAll('.date-field').forEach((wrapper) => {
        const text = wrapper.querySelector('.date-text');
        const picker = wrapper.querySelector('.date-native');
        const button = wrapper.querySelector('.date-picker-btn');
        if (!text) return;

        text.placeholder = fmt.placeholder;
        text.dataset.iso = '';
        if (button) {
            button.setAttribute('aria-label', _dateFieldText('calendar'));
            button.title = _dateFieldText('calendar');
            button.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="3"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>';
        }

        text.addEventListener('change', () => {
            const value = text.value.trim();
            if (!value) {
                setDateFieldIso(text.id, '');
                if (onChange) onChange();
                return;
            }
            const iso = parseLocalizedDate(value);
            if (iso) {
                setDateFieldIso(text.id, iso);
                if (onChange) onChange();
            } else {
                text.classList.add('invalid');
                text.setAttribute('aria-invalid', 'true');
                text.title = _dateFieldText('invalid') + fmt.placeholder;
            }
        });
        text.addEventListener('keydown', (evt) => {
            if (evt.key === 'Enter') text.dispatchEvent(new Event('change'));
        });

        if (button && picker) {
            button.addEventListener('click', () => {
                picker.value = text.dataset.iso || '';
                try {
                    picker.showPicker();
                } catch (e) {
                    picker.focus();
                    picker.click();
                }
            });
            picker.addEventListener('change', () => {
                setDateFieldIso(text.id, picker.value);
                if (onChange) onChange();
            });
        }
    });
}

/* ---------- Export CSV (partagé entre data_comparison.html,
   fault_history.html et maintenance_history.html) ----------
 *
 * Mise en forme adaptée à la langue de l'interface, pour que le fichier
 * s'ouvre correctement d'un double-clic dans Excel :
 *   - FR : séparateur ";" et virgule décimale (Excel FR sépare les colonnes
 *     sur ";" — avec "," tout atterrissait dans une seule colonne — et prend
 *     "6.2" pour du texte, voire une date) ;
 *   - EN : séparateur "," et point décimal.
 * Les nombres sont exportés en tant que nombres (calculs/tris possibles
 * dans Excel), les textes commençant par = + - @ sont neutralisés (injection
 * de formule), et les dates suivent le format de la langue (formatDateTime). */

function csvDelimiter(lang = navLang()) {
    return lang === 'en' ? ',' : ';';
}

function toCsvValue(v, lang = navLang()) {
    if (v === null || v === undefined) return '';
    const delimiter = csvDelimiter(lang);
    let s;
    if (typeof v === 'number') {
        if (!Number.isFinite(v)) return '';
        // toPrecision(12) : retire le bruit binaire (6.200000000000001 → 6.2).
        s = String(parseFloat(v.toPrecision(12)));
        if (lang !== 'en') s = s.replace('.', ',');
        return s;
    }
    s = String(v);
    // Injection de formule (Excel/LibreOffice interprètent =, +, -, @ en tête).
    if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
    if (s.includes('"') || s.includes(delimiter) || /[\r\n]/.test(s)) {
        return '"' + s.replace(/"/g, '""') + '"';
    }
    return s;
}

/**
 * Déclenche le téléchargement d'un CSV construit à partir d'une ligne
 * d'en-tête et d'un tableau de lignes. Ajoute un BOM UTF-8 : Excel (FR)
 * n'auto-détecte pas l'encodage sans lui et afficherait les accents des
 * en-têtes de colonnes de travers. Déjà utilisé par data_comparison.html
 * (export par cellule), promu ici pour être réutilisé par les pages
 * d'historique (pannes, maintenance).
 */
function downloadCsv(filename, headerRow, rows) {
    const lang = navLang();
    const delimiter = csvDelimiter(lang);
    const lines = [headerRow, ...rows].map((row) => row.map((v) => toCsvValue(v, lang)).join(delimiter));
    const csvContent = String.fromCharCode(0xFEFF) + lines.join('\r\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}
