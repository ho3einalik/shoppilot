import base64
import hashlib
import ipaddress
import logging
import socket
import urllib.parse
from django.conf import settings
from rest_framework.exceptions import ValidationError
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# Derive deterministic 32-byte Fernet key from Django SECRET_KEY
def _get_fernet_key() -> bytes:
    custom_key = getattr(settings, 'INTEGRATION_ENCRYPTION_KEY', None)
    if custom_key:
        raw_key = custom_key.encode('utf-8')
    else:
        raw_key = settings.SECRET_KEY.encode('utf-8')
    digest = hashlib.sha256(raw_key).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(plain_text: str) -> str:
    """
    Encrypts a sensitive plaintext secret at rest using Fernet symmetric encryption.
    Prepends 'enc:' prefix so encrypted values can be identified reliably.
    """
    if not plain_text:
        return ""
    if plain_text.startswith("enc:"):
        # Already encrypted
        return plain_text

    fernet = Fernet(_get_fernet_key())
    encrypted = fernet.encrypt(plain_text.encode('utf-8')).decode('utf-8')
    return f"enc:{encrypted}"


def decrypt_secret(cipher_text: str) -> str:
    """
    Decrypts an encrypted secret. If value is not prefixed with 'enc:',
    returns as-is for backward compatibility.
    """
    if not cipher_text:
        return ""
    if not cipher_text.startswith("enc:"):
        return cipher_text

    try:
        fernet = Fernet(_get_fernet_key())
        raw_token = cipher_text[4:].encode('utf-8')
        decrypted = fernet.decrypt(raw_token).decode('utf-8')
        return decrypted
    except (InvalidToken, Exception) as e:
        logger.error(f"Failed to decrypt secret: {e}")
        return ""


def mask_secret(value: str) -> str:
    """
    Masks a secret value for safe presentation in APIs and user interfaces.
    Never returns the real plain text.
    """
    if not value:
        return ""
    
    # Decrypt if needed to determine original length or keep it generic
    decrypted = decrypt_secret(value) if value.startswith("enc:") else value
    if not decrypted:
        return ""

    if len(decrypted) <= 6:
        return "••••••••"
    return f"{decrypted[:2]}••••••••{decrypted[-2:]}"


# SSRF Protection: IP Ranges that are blocked from custom webhooks / API URLs
BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network('0.0.0.0/8'),
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('100.64.0.0/10'),
    ipaddress.ip_network('127.0.0.0/8'),
    ipaddress.ip_network('169.254.0.0/16'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.0.0.0/24'),
    ipaddress.ip_network('192.0.2.0/24'),
    ipaddress.ip_network('192.88.99.0/24'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('198.18.0.0/15'),
    ipaddress.ip_network('198.51.100.0/24'),
    ipaddress.ip_network('203.0.113.0/24'),
    ipaddress.ip_network('224.0.0.0/4'),
    ipaddress.ip_network('240.0.0.0/4'),
    ipaddress.ip_network('255.255.255.255/32'),
    # IPv6
    ipaddress.ip_network('::/128'),
    ipaddress.ip_network('::1/128'),
    ipaddress.ip_network('::ffff:0:0/96'),
    ipaddress.ip_network('100::/64'),
    ipaddress.ip_network('2001:db8::/32'),
    ipaddress.ip_network('fc00::/7'),
    ipaddress.ip_network('fe80::/10'),
    ipaddress.ip_network('ff00::/8'),
]


def validate_custom_url(url: str, allowed_schemes=('https', 'http')) -> str:
    """
    Validates a URL against Server-Side Request Forgery (SSRF) vulnerabilities.
    Blocks private IP addresses, loopback addresses, metadata endpoints, and non-HTTP schemes.
    """
    if not url:
        return ""

    url = url.strip()
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        raise ValidationError("ساختار آدرس اینترنتی وارد شده نامعتبر است.")

    if parsed.scheme.lower() not in allowed_schemes:
        raise ValidationError(f"پروتکل آدرس اینترنتی باید یکی از موارد {' یا '.join(allowed_schemes)} باشد.")

    hostname = parsed.hostname
    if not hostname:
        raise ValidationError("دامنه یا آدرس میزبان در URL مشخص نشده است.")

    # Check against known dangerous hostnames
    low_host = hostname.lower()
    if low_host in ('localhost', '127.0.0.1', '::1', '0.0.0.0', 'metadata.google.internal', 'instance-data'):
        raise ValidationError(f"دسترسی به آدرس داخلی '{hostname}' به دلایل امنیتی مجاز نیست.")

    # DNS resolution check
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        # If host cannot be resolved, reject or allow if testing?
        # In strict SSRF validation, an unresolvable host cannot be connected to.
        raise ValidationError(f"دامنه '{hostname}' در شبکه قابل تفکیک (DNS Resolve) نمی‌باشد.")

    for family, _, _, _, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            for net in BLOCKED_IP_NETWORKS:
                if ip_obj in net:
                    raise ValidationError(
                        f"آدرس وارد شده به آدرس شبکه خصوصی یا محافظت‌شده ({ip_str}) اشاره می‌کند و دسترسی به آن مسدود است."
                    )
        except ValueError:
            pass

    return url
