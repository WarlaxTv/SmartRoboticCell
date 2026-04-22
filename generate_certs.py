import datetime
import ipaddress
import os

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def generate_self_signed_cert(cert_path, key_path, hostname="localhost"):
    print(f"Génération des certificats pour {hostname}...")

    # Génération de la clé privée
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Création du sujet et de l'émetteur
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "FR"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Ile-de-France"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Paris"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Smart Robotic Cell V2"),
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
    ])

    # Gestion des noms alternatifs (SAN) pour éviter les erreurs de certificat
    san_list = [x509.DNSName(hostname)]
    if hostname == "localhost":
        san_list.append(x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")))

    # Création du certificat
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.now(datetime.UTC)
    ).not_valid_after(
        # Valide pour 1 an
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365)
    ).add_extension(
        x509.SubjectAlternativeName(san_list),
        critical=False,
    ).sign(private_key, hashes.SHA256())

    # Sauvegarde du certificat
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    # Sauvegarde de la clé privée
    with open(key_path, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))
    print(f"✅ Certificats générés avec succès :\n - {cert_path}\n - {key_path}")

if __name__ == "__main__":
    os.makedirs("certs", exist_ok=True)
    generate_self_signed_cert(
        "certs/opcua_cert.pem",
        "certs/opcua_key.pem",
        "urn:freeopcua:python:server",
    )
    generate_self_signed_cert("certs/web_cert.pem", "certs/web_key.pem", "localhost")
