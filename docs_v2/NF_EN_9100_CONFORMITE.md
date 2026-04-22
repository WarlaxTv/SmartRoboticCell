# Stratégie de Conformité - NF EN 9100

Le projet **Smart Robotic Cell V2** s'inscrit dans un contexte industriel strict (Aéronautique, Espace, Défense). La conception du système a été fondamentalement revue pour répondre aux exigences de la norme **NF EN 9100**, qui met l'accent sur la gestion des risques, la traçabilité et la maîtrise de la qualité.

## 1. Gestion des Risques (Chapitre 6.1 et 8.1.1)

### Risque identifié : Prise de contrôle à distance (Remote Control)
Dans la version précédente (POC V1), il était possible d'armer, de démarrer et d'acquitter des défauts de la cellule robotique à distance via une interface web. 

**Analyse du risque :**
La prise de contrôle à distance de systèmes robotiques lourds présente un risque critique pour la sécurité des opérateurs (écrasement, collision) et pour l'intégrité du matériel si un mouvement est déclenché sans contact visuel direct avec la cellule.

**Mesure d'atténuation (Mitigation) :**
- **Suppression totale des commandes d'actionnement à distance.** L'architecture V2 est strictement "Read-Only" (Lecture Seule) pour l'interface web.
- Les actions de démarrage et d'acquittement doivent être réalisées localement sur l'IHM physique de la machine par un opérateur qualifié.

**Note POC (Environnement de démonstration) :**
Une API de simulation existe uniquement pour les besoins de soutenance (injection d'états sur le serveur OPC UA). Cette API est **restreinte** au rôle `MAINTENANCE` et n'est pas destinée à un usage en production.

## 2. Sûreté de Fonctionnement et Sécurisation des Données (Chapitre 7.1.3 et 8.4)

- **Protocole Industriel Standardisé :** L'utilisation de l'OPC UA (Standard IEC 62541) garantit une interopérabilité et une fiabilité de la transmission des données d'état.
- **Chiffrement des Communications :** Toutes les communications entre les cellules robotiques (serveur OPC UA) et le système de supervision (Client OPC UA / Web) sont chiffrées (Basic256Sha256) via des certificats SSL/TLS.
- **Protection de l'Interface Web :** Le tableau de bord est accessible uniquement en HTTPS, garantissant l'intégrité des informations de supervision remontées aux responsables de production.

## 2.1. Bonnes pratiques OWASP / ISO (Sécurité Applicative)

- **Gestion des secrets :** la clé JWT n'est pas figée dans le code et peut être fournie via variable d'environnement (`SRC_JWT_SECRET_KEY`).
- **Contrôle d'accès (RBAC) :** les endpoints sensibles (ex: simulation POC) sont protégés par des rôles.
- **Réduction de surface d'attaque :** les mécanismes de simulation sont explicitement séparés des fonctions de supervision.

## 3. Configuration et Traçabilité (Chapitre 8.1.2)

- L'état de chaque cellule ("EN_PRODUCTION", "DEFAUT", "ARRET"), sa température moteur et son compteur de pièces sont échantillonnés en temps réel et horodatés via le protocole OPC UA.
- Le code source est structuré et versionné. L'historique des modifications depuis le POC V1 est conservé pour assurer la continuité numérique (Archivage dans `v1_poc/`).

## 4. Qualité logicielle / preuves (PEP8, tests unitaires)

- Un socle de qualité est maintenu (formatage, lint) afin de réduire les écarts aux conventions de code et de faciliter la revue.
- Des tests unitaires valident les composants critiques (auth, rôles, endpoints), et servent de preuve de non-régression.

## 5. Données personnelles (RGPD - principes)

- Le système ne traite que des données minimales (identifiant utilisateur pour la traçabilité des demandes).
- Les journaux et historiques sont utilisés à des fins de sécurité/qualité (traçabilité) et doivent être limités à ce qui est nécessaire.

---
*Ce document sert de preuve documentaire (Documented Information) pour les audits de certification du système de management de la qualité (SMQ) de l'entreprise.*
