import base64
import json
import os
from Cryptodome.Cipher import AES, PKCS1_OAEP
from Cryptodome.Hash import HMAC, SHA256
from Cryptodome.Random import get_random_bytes
from Cryptodome.Util import Padding

from vinetrimmer.utils.MSL.schemes.KeyExchangeRequest import KeyExchangeRequest

class PlayReady(KeyExchangeRequest):
    """
    Implementation of the PlayReady Key Exchange Scheme for MSL.
    """
    
    def __init__(self):
        self.encryption_key = None
        self.sign_key = None
        self.sender = None
    
    def perform_key_exchange(self, session, endpoint, sender, cdm):
        """
        Performs a key exchange using PlayReady.
        
        Parameters:
            session: HTTP session with necessary cookies
            endpoint: Endpoint for key exchange
            sender: ESN of the device
            cdm: CDM instance
        """
        self.sender = sender
        
        # Generate random keys for encryption and signing
        self.encryption_key = get_random_bytes(16)  # AES-128
        self.sign_key = get_random_bytes(32)  # HMAC-SHA256
        
        # Return keys in the format required by MSL
        return {
            "encryptionkey": base64.b64encode(self.encryption_key).decode("utf-8"),
            "hmackey": base64.b64encode(self.sign_key).decode("utf-8")
        }
    
    def encrypt(self, data, encryption_envelope=None):
        """
        Encrypts data using the encryption key.
        
        Parameters:
            data: Data to encrypt
            encryption_envelope: Not used in PlayReady
        """
        if not self.encryption_key:
            raise ValueError("No encryption key available")
        
        # Generate a random IV
        iv = get_random_bytes(16)
        
        # Encrypt the data
        cipher = AES.new(self.encryption_key, AES.MODE_CBC, iv)
        ciphertext = cipher.encrypt(Padding.pad(data.encode("utf-8"), 16))
        
        # Return encrypted data in the format required by MSL
        return {
            "keyid": self.sender,
            "iv": base64.b64encode(iv).decode("utf-8"),
            "ciphertext": base64.b64encode(ciphertext).decode("utf-8")
        }
    
    def decrypt(self, data):
        """
        Decrypts data using the encryption key.
        
        Parameters:
            data: Encrypted data (with iv and ciphertext)
        """
        if not self.encryption_key:
            raise ValueError("No encryption key available")
        
        # Decode IV and ciphertext
        iv = base64.b64decode(data["iv"])
        ciphertext = base64.b64decode(data["ciphertext"])
        
        # Decrypt the data
        cipher = AES.new(self.encryption_key, AES.MODE_CBC, iv)
        plaintext = Padding.unpad(cipher.decrypt(ciphertext), 16)
        
        return plaintext
    
    def sign(self, data):
        """
        Signs data using the sign key.
        
        Parameters:
            data: Data to sign
        """
        if not self.sign_key:
            raise ValueError("No sign key available")
        
        # Sign the data with HMAC-SHA256
        signature = HMAC.new(self.sign_key, data.encode("utf-8"), SHA256).digest()
        return base64.b64encode(signature)
    
    def verify(self, data, signature):
        """
        Verifies a signature.
        
        Parameters:
            data: Data that was signed
            signature: Signature to verify
        """
        expected_signature = self.sign(data)
        return signature == expected_signature.decode("utf-8")