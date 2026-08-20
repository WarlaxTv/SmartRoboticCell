import datetime
import ipaddress
import os
import platform
import subprocess

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def trust_certificate_windows(cert_path: str) -> None:
    """Ajoute le certificat au magasin de confiance Windows de l'utilisateur courant.

    Corrige l'affichage "site non sécurisé" du navigateur : un certificat
    auto-signé n'est jamais reconnu comme sûr tant qu'il n'a pas été ajouté
    explicitement au magasin de confiance. -user (CurrentUser\\Root) ne
    nécessite pas de droits administrateur, contrairement à -store Root
    (LocalMachine). Sans effet et sans erreur bloquante sur les autres OS.
    """

    if platform.system() != "Windows":
        print(
            "ℹ️  Ajout au magasin de confiance ignoré (non-Windows). "
            "Le certificat reste auto-signé : le navigateur affichera "
            "un avertissement tant qu'il n'est pas approuvé manuellement."
        )
        return
    try:
        # certutil est un outil système Windows standard (chemin non contrôlé
        # par un utilisateur) et l'argument cert_path est toujours un chemin
        # local fixe fourni par ce script, jamais une entrée utilisateur.
        cmd = ["certutil", "-user", "-addstore", "Root", cert_path]  # noqa: S607
        subprocess.run(cmd, check=True, capture_output=True, text=True)  # noqa: S603
        print(
            f"✅ Certificat {cert_path} ajouté au magasin de confiance "
            "Windows (utilisateur courant)."
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(
            f"⚠️  Impossible d'ajouter automatiquement {cert_path} au "
            f"magasin de confiance ({exc}). Le site restera affiché comme "
            "non sécurisé tant que le certificat n'est pas approuvé "
            "manuellement (double-clic sur le fichier .pem/.crt > "
            "Installer le certificat > Utilisateur actuel > Autorités de "
            "certification racines de confiance)."
        )


def generate_self_signed_cert(cert_path, key_path, hostname="localhost"):
    print(f"Génération des certificats pour {hostname}...")

    # Génération de la clé privée
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Création du sujet et de l'émetteur
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "FR"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Ile-de-France"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Paris"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Smart Robotic Cell V2"),
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        ]
    )

    # Gestion des noms alternatifs (SAN) pour éviter les erreurs de certificat
    san_list = [x509.DNSName(hostname)]
    if hostname == "localhost":
        san_list.append(x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")))

    # Création du certificat
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.UTC))
        .not_valid_after(
            # Valide pour 1 an
            datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(days=365)
        )
        .add_extension(
            x509.SubjectAlternativeName(san_list),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    # Sauvegarde du certificat
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    # Sauvegarde de la clé privée
    with open(key_path, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    print(f"✅ Certificats générés avec succès :\n - {cert_path}\n - {key_path}")


if __name__ == "__main__":
    os.makedirs("certs", exist_ok=True)

    # Régénérer un certificat à chaque démarrage invalide la confiance déjà
    # accordée par le magasin Windows (nouveau certificat = nouvelle preuve
    # de confiance à chaque fois). On ne (re)génère donc que si absent.
    if not (
        os.path.exists("certs/opcua_cert.pem") and os.path.exists("certs/opcua_key.pem")
    ):
        generate_self_signed_cert(
            "certs/opcua_cert.pem",
            "certs/opcua_key.pem",
            "urn:freeopcua:python:server",
        )
    else:
        print("Certificat OPC UA déjà présent, réutilisation.")

    web_cert_existed = os.path.exists("certs/web_cert.pem") and os.path.exists(
        "certs/web_key.pem"
    )
    if not web_cert_existed:
        generate_self_signed_cert(
            "certs/web_cert.pem", "certs/web_key.pem", "localhost"
        )
    else:
        print("Certificat Web déjà présent, réutilisation.")

    # On (ré)essaie l'ajout au magasin de confiance à chaque lancement : sans
    # effet si déjà présent, et ça rattrape le cas d'un premier certificat
    # jamais approuvé.
    trust_certificate_windows("certs/web_cert.pem")
