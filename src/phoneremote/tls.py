"""HTTPS for the phone page.

Browsers only allow some features on HTTPS pages: keeping the screen awake,
motion sensors (tilt-to-point) and installing the page as an app. HTTPS also
stops an attacker on the network from swapping the page's JavaScript.

Two options:
- A certificate the user supplies (--cert/--key), e.g. for a domain name that
  resolves to the laptop. Phones trust it with no warning.
- A self-signed certificate made here and kept in the config folder. The phone
  shows a "not private" warning once, which the user accepts. That unlocks the
  features above but, unlike a real certificate, can't stop an attacker who is
  already intercepting traffic before that first visit.
"""

import datetime
import hashlib
import ipaddress
import os
import ssl

VALID_DAYS = 800        # Apple rejects TLS certificates valid for more than 825 days
RENEW_BEFORE_DAYS = 30


def _needs_new(cert_path, ip_addresses):
    from cryptography import x509

    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    except (OSError, ValueError):
        return True
    expires = cert.not_valid_after_utc
    if expires - datetime.datetime.now(datetime.timezone.utc) < datetime.timedelta(days=RENEW_BEFORE_DAYS):
        return True
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return True
    have = {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
    return not set(ip_addresses) <= have


def self_signed(folder, ip_addresses, hostname):
    """Return (cert path, key path), making a new certificate when needed.

    A new one is made when there is none, it expires soon, or it doesn't cover
    every address in ip_addresses (the laptop moved to another network). Each
    new certificate means the phone shows its warning once more.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    cert_path, key_path = folder / "https-cert.pem", folder / "https-key.pem"
    ip_addresses = sorted(set(ip_addresses) | {"127.0.0.1"})
    if key_path.exists() and not _needs_new(cert_path, ip_addresses):
        return cert_path, key_path

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Phone Remote on {hostname}"[:64])])
    now = datetime.datetime.now(datetime.timezone.utc)
    dns = {hostname, f"{hostname}.local", "localhost"}
    san = [x509.DNSName(d) for d in sorted(dns) if d and all(c.isalnum() or c in ".-" for c in d)]
    san += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ip_addresses]
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key_pem)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def server_context(cert_path, key_path):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert_path, key_path)
    return context


def fingerprint(cert_path):
    """SHA-256 fingerprint as shown by browsers' certificate viewers."""
    der = ssl.PEM_cert_to_DER_cert(cert_path.read_text(encoding="ascii"))
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))
