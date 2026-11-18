"""
LaptopShare Security Module
Handles dynamic TLS certificate generation, SSL context creation,
and connection PIN generation / verification.
"""

import os
import ssl
import random
import datetime
from pathlib import Path
from typing import Tuple

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from .config import get_app_data_dir

def generate_pin() -> str:
    """Generates a cryptographically secure 6-digit connection PIN."""
    sys_rand = random.SystemRandom()
    return f"{sys_rand.randint(100000, 999999):06d}"

def ensure_tls_certificate() -> Tuple[str, str]:
    """
    Ensures an ephemeral or persistent TLS certificate and private key exist for this device.
    Returns (cert_file_path, key_file_path).
    """
    cert_dir = get_app_data_dir() / "certs"
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / "laptopshare.crt"
    key_path = cert_dir / "laptopshare.key"

    # If certificate already exists and has not expired, reuse it
    if cert_path.exists() and key_path.exists():
        try:
            with open(cert_path, "rb") as f:
                cert_data = x509.load_pem_x509_certificate(f.read())
                # Check expiration
                if cert_data.not_valid_after_utc > datetime.datetime.now(datetime.timezone.utc):
                    return str(cert_path), str(key_path)
        except Exception:
            pass

    # Generate a new 2048-bit RSA key
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "LaptopShare Direct LAN"),
        x509.NameAttribute(NameOID.COMMON_NAME, "LaptopShare-Peer"),
    ])

    import ipaddress
    san_list = [
        x509.DNSName("localhost"),
        x509.DNSName("LaptopShare-Peer"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ]

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName(san_list),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    # Write key to file
    with open(key_path, "wb") as f:
        f.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    # Write cert to file
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    return str(cert_path), str(key_path)

def create_server_ssl_context() -> ssl.SSLContext:
    """Creates a TLS server context using the generated certificate."""
    cert_path, key_path = ensure_tls_certificate()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
    # Prefer strong ciphers and disable obsolete protocols
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx

def create_client_ssl_context() -> ssl.SSLContext:
    """
    Creates a TLS client context for connecting to peer LaptopShare instances.
    Since peers use dynamically generated self-signed certificates on direct LAN,
    we skip certificate authority verification, relying on PIN authentication.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx
