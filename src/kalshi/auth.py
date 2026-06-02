import base64
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def load_private_key(pem_path: str):
    with open(pem_path, 'rb') as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def build_auth_headers(api_key_id: str, private_key, method: str, path: str) -> dict:
    """Sign a Kalshi v2 API request.

    path must be the full URL path including /trade-api/v2 prefix.
    Kalshi requires RSA-PSS with SHA-256 (not PKCS1v15).
    """
    timestamp_ms = str(int(time.time() * 1000))
    message = (timestamp_ms + method.upper() + path).encode('utf-8')
    pss = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH)
    signature = private_key.sign(message, pss, hashes.SHA256())
    return {
        'KALSHI-ACCESS-KEY': api_key_id,
        'KALSHI-ACCESS-SIGNATURE': base64.b64encode(signature).decode('utf-8'),
        'KALSHI-ACCESS-TIMESTAMP': timestamp_ms,
        'Content-Type': 'application/json',
    }
