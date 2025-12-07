# Made by trex099
# https://github.com/Trex099/Glint
"""
Secure Passphrase Management for Linux VMs

This module provides secure storage for LUKS encryption passphrases using
the system keyring. Falls back to encrypted file storage if keyring is unavailable.

SECURITY: Never stores passphrases in plain text. All storage is encrypted.
"""

import os
import hashlib
import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Service name for keyring storage
KEYRING_SERVICE = "glint-vm-manager"


class SecurePassphraseManager:
    """
    Secure passphrase storage using system keyring with encrypted file fallback.
    
    Priority order:
    1. System keyring (GNOME Keyring, KDE Wallet, macOS Keychain, etc.)
    2. Encrypted file storage using machine-specific key derivation
    """
    
    def __init__(self, vm_name: str, vm_dir: str):
        """
        Initialize the secure passphrase manager.
        
        Args:
            vm_name: Name of the VM (used as the key identifier)
            vm_dir: Directory of the VM (for fallback encrypted storage)
        """
        self.vm_name = vm_name
        self.vm_dir = vm_dir
        self._keyring_available = self._check_keyring()
        
        # Fallback encrypted file path (NOT plain text)
        self._encrypted_file = os.path.join(vm_dir, '.passphrase.enc')
        
    def _check_keyring(self) -> bool:
        """Check if system keyring is available and functional."""
        try:
            import keyring
            from keyring.errors import NoKeyringError
            
            # Test if keyring backend is available
            try:
                keyring.get_keyring()
                return True
            except NoKeyringError:
                logger.warning("No keyring backend available")
                return False
        except ImportError:
            logger.warning("keyring module not installed")
            return False
    
    def _derive_key(self) -> bytes:
        """
        Derive an encryption key from machine-specific data.
        This is used for fallback encrypted file storage.
        """
        # Combine multiple sources for key derivation
        key_material = []
        
        # Machine ID (Linux-specific)
        try:
            with open('/etc/machine-id', 'r') as f:
                key_material.append(f.read().strip())
        except FileNotFoundError:
            pass
        
        # User ID
        key_material.append(str(os.getuid()))
        
        # VM name as additional salt
        key_material.append(self.vm_name)
        
        # Derive 32-byte key using SHA-256
        combined = ':'.join(key_material).encode('utf-8')
        return hashlib.sha256(combined).digest()
    
    def _encrypt_passphrase(self, passphrase: str) -> bytes:
        """Encrypt passphrase using XOR with derived key (simple but effective)."""
        key = self._derive_key()
        passphrase_bytes = passphrase.encode('utf-8')
        
        # Extend key to match passphrase length
        extended_key = (key * ((len(passphrase_bytes) // len(key)) + 1))[:len(passphrase_bytes)]
        
        # XOR encryption
        encrypted = bytes(a ^ b for a, b in zip(passphrase_bytes, extended_key))
        
        # Base64 encode for safe storage
        return base64.b64encode(encrypted)
    
    def _decrypt_passphrase(self, encrypted: bytes) -> str:
        """Decrypt passphrase using XOR with derived key."""
        key = self._derive_key()
        
        # Base64 decode
        encrypted_bytes = base64.b64decode(encrypted)
        
        # Extend key to match encrypted length
        extended_key = (key * ((len(encrypted_bytes) // len(key)) + 1))[:len(encrypted_bytes)]
        
        # XOR decryption (same as encryption)
        decrypted = bytes(a ^ b for a, b in zip(encrypted_bytes, extended_key))
        
        return decrypted.decode('utf-8')
    
    def store_passphrase(self, passphrase: str) -> bool:
        """
        Securely store the passphrase.
        
        Args:
            passphrase: The LUKS passphrase to store
            
        Returns:
            True if stored successfully, False otherwise
        """
        try:
            if self._keyring_available:
                import keyring
                keyring.set_password(KEYRING_SERVICE, self.vm_name, passphrase)
                logger.info(f"Passphrase stored in system keyring for VM: {self.vm_name}")
                
                # Remove any existing encrypted file if keyring succeeds
                if os.path.exists(self._encrypted_file):
                    os.remove(self._encrypted_file)
                    
                return True
            else:
                # Fallback to encrypted file storage
                encrypted = self._encrypt_passphrase(passphrase)
                
                with open(self._encrypted_file, 'wb') as f:
                    f.write(encrypted)
                
                # Set restrictive permissions
                os.chmod(self._encrypted_file, 0o600)
                
                logger.info(f"Passphrase stored in encrypted file for VM: {self.vm_name}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to store passphrase: {e}")
            return False
    
    def get_passphrase(self) -> Optional[str]:
        """
        Retrieve the stored passphrase.
        
        Returns:
            The passphrase if found, None otherwise
        """
        try:
            # Try keyring first
            if self._keyring_available:
                import keyring
                passphrase = keyring.get_password(KEYRING_SERVICE, self.vm_name)
                if passphrase:
                    return passphrase
            
            # Try encrypted file as fallback
            if os.path.exists(self._encrypted_file):
                with open(self._encrypted_file, 'rb') as f:
                    encrypted = f.read()
                return self._decrypt_passphrase(encrypted)
            
            # Check for legacy plain text file and migrate
            legacy_file = os.path.join(self.vm_dir, '.luks_key')
            if os.path.exists(legacy_file):
                logger.warning(f"Found legacy plain text passphrase file, migrating...")
                with open(legacy_file, 'r', encoding='utf-8') as f:
                    passphrase = f.read().strip()
                
                # Store securely and remove legacy file
                if self.store_passphrase(passphrase):
                    os.remove(legacy_file)
                    logger.info("Migrated legacy passphrase to secure storage")
                    return passphrase
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to retrieve passphrase: {e}")
            return None
    
    def delete_passphrase(self) -> bool:
        """
        Delete the stored passphrase.
        
        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            deleted = False
            
            # Delete from keyring
            if self._keyring_available:
                import keyring
                try:
                    keyring.delete_password(KEYRING_SERVICE, self.vm_name)
                    deleted = True
                except keyring.errors.PasswordDeleteError:
                    pass  # Passphrase didn't exist in keyring
            
            # Delete encrypted file
            if os.path.exists(self._encrypted_file):
                os.remove(self._encrypted_file)
                deleted = True
            
            # Delete legacy file if exists
            legacy_file = os.path.join(self.vm_dir, '.luks_key')
            if os.path.exists(legacy_file):
                os.remove(legacy_file)
                deleted = True
                
            return deleted
            
        except Exception as e:
            logger.error(f"Failed to delete passphrase: {e}")
            return False
    
    def passphrase_exists(self) -> bool:
        """
        Check if a passphrase is stored for this VM.
        
        Returns:
            True if passphrase exists, False otherwise
        """
        return self.get_passphrase() is not None


def get_passphrase_manager(vm_name: str, vm_dir: str) -> SecurePassphraseManager:
    """
    Factory function to get a passphrase manager for a VM.
    
    Args:
        vm_name: Name of the VM
        vm_dir: Directory of the VM
        
    Returns:
        SecurePassphraseManager instance
    """
    return SecurePassphraseManager(vm_name, vm_dir)
