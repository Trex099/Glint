# Made by trex099
# https://github.com/Trex099/Glint
"""
LUKS Encryption Support Module for Linux VMs

This module provides REAL functionality to manage LUKS encryption for VM disks
using qemu-img with proper LUKS format support.
"""

import os
import subprocess
import tempfile
import json
import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class EncryptionConfig:
    """Encryption configuration"""
    passphrase: str
    cipher: str = "aes-xts-plain64"
    key_size: int = 512
    iter_time: int = 2000  # PBKDF iteration time in ms


@dataclass
class EncryptionStatus:
    """Encryption status"""
    is_encrypted: bool
    cipher: Optional[str] = None
    key_size: Optional[int] = None
    format: Optional[str] = None


class LUKSManager:
    """
    REAL LUKS encryption manager for Linux VMs using qemu-img.
    
    Uses qemu-img's native LUKS support for creating and managing
    encrypted qcow2 disk images.
    """
    
    def __init__(self, vm_name: str):
        """
        Initialize LUKS manager.
        
        Args:
            vm_name: Name of the VM
        """
        from ..main import get_vm_paths
        
        self.vm_name = vm_name
        self.paths = get_vm_paths(vm_name)
        self.config_file = os.path.join(self.paths["dir"], "encryption.json")
        self.logger = logging.getLogger(f'glint.luks.{vm_name}')
    
    def _run_qemu_img(self, args: list, passphrase: Optional[str] = None) -> Tuple[bool, str]:
        """
        Run qemu-img command with optional passphrase secret.
        
        Args:
            args: Command arguments (without 'qemu-img' prefix)
            passphrase: Optional passphrase for encryption operations
            
        Returns:
            Tuple of (success, output/error message)
        """
        cmd = ['qemu-img'] + args
        
        try:
            if passphrase:
                # Create a temporary file for the passphrase (secure)
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.key') as f:
                    f.write(passphrase)
                    temp_key_file = f.name
                os.chmod(temp_key_file, 0o600)
                
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                finally:
                    # Always clean up the temp file
                    if os.path.exists(temp_key_file):
                        os.remove(temp_key_file)
            else:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                return True, result.stdout
            else:
                return False, result.stderr
                
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)
    
    def _check_disk_encryption_real(self, disk_path: str) -> Tuple[bool, Dict]:
        """
        Check if a disk is LUKS encrypted using qemu-img info.
        
        Returns:
            Tuple of (is_encrypted, info_dict)
        """
        if not os.path.exists(disk_path):
            return False, {}
        
        try:
            # Use qemu-img info with JSON output
            result = subprocess.run(
                ['qemu-img', 'info', '--output=json', disk_path],
                capture_output=True, text=True, timeout=30
            )
            
            if result.returncode != 0:
                return False, {}
            
            info = json.loads(result.stdout)
            
            # Check for encryption in the format-specific info
            encrypt_info = info.get('format-specific', {}).get('data', {}).get('encrypt', {})
            if encrypt_info:
                return True, {
                    'format': encrypt_info.get('format', 'luks'),
                    'cipher': encrypt_info.get('cipher-alg', 'aes-256'),
                    'cipher_mode': encrypt_info.get('cipher-mode', 'xts'),
                }
            
            # Also check if the format itself indicates encryption
            if 'luks' in info.get('format', '').lower():
                return True, {'format': 'luks'}
            
            return False, info
            
        except (json.JSONDecodeError, subprocess.TimeoutExpired, Exception) as e:
            self.logger.warning(f"Error checking disk encryption: {e}")
            return False, {}
    
    def get_encryption_status(self) -> Dict[str, EncryptionStatus]:
        """
        Get encryption status for all disks.
        
        Returns:
            Dictionary mapping disk names to encryption status
        """
        try:
            from .multi_disk import DiskManager
            disk_manager = DiskManager(self.vm_name)
            disks = disk_manager.list_disks()
            
            status = {}
            for disk in disks:
                is_encrypted, info = self._check_disk_encryption_real(disk.path)
                
                status[disk.name] = EncryptionStatus(
                    is_encrypted=is_encrypted,
                    cipher=info.get('cipher') if is_encrypted else None,
                    key_size=info.get('key_size') if is_encrypted else None,
                    format=info.get('format') if is_encrypted else None
                )
            
            return status
        except Exception as e:
            self.logger.error(f"Error getting encryption status: {e}")
            return {}
    
    def _is_disk_encrypted(self, disk_path: str) -> bool:
        """Check if a disk is encrypted (simple wrapper)"""
        is_encrypted, _ = self._check_disk_encryption_real(disk_path)
        return is_encrypted
    
    def encrypt_disk(self, disk_path: str, config: EncryptionConfig) -> Tuple[bool, str]:
        """
        REAL: Encrypt a disk using qemu-img convert with LUKS.
        
        Args:
            disk_path: Path to the source disk (will be converted)
            config: Encryption configuration
            
        Returns:
            Tuple of (success, encrypted_path or error message)
        """
        if not os.path.exists(disk_path):
            return False, f"Source disk not found: {disk_path}"
        
        # Generate encrypted disk path
        encrypted_path = disk_path.replace('.qcow2', '_encrypted.qcow2')
        
        # Create a temporary file for the passphrase
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.key') as f:
                f.write(config.passphrase)
                temp_key_file = f.name
            os.chmod(temp_key_file, 0o600)
            
            # Build qemu-img convert command for LUKS encryption
            # qemu-img convert -f qcow2 -O qcow2 
            #   -o encrypt.format=luks,encrypt.key-secret=sec0
            #   --object secret,id=sec0,file=/path/to/keyfile
            #   source.qcow2 encrypted.qcow2
            
            encrypt_opts = [
                f"encrypt.format=luks",
                f"encrypt.key-secret=sec0",
            ]
            
            # Add optional parameters if specified
            if config.iter_time:
                encrypt_opts.append(f"encrypt.iter-time={config.iter_time}")
            
            cmd = [
                'qemu-img', 'convert',
                '-f', 'qcow2',
                '-O', 'qcow2',
                '-o', ','.join(encrypt_opts),
                '--object', f'secret,id=sec0,file={temp_key_file}',
                disk_path,
                encrypted_path
            ]
            
            self.logger.info(f"Encrypting disk: {disk_path} -> {encrypted_path}")
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            
            if result.returncode == 0:
                # Verify the encryption was successful
                is_encrypted, _ = self._check_disk_encryption_real(encrypted_path)
                if is_encrypted:
                    self.logger.info(f"Successfully encrypted disk: {encrypted_path}")
                    return True, encrypted_path
                else:
                    return False, "Encryption completed but verification failed"
            else:
                self.logger.error(f"Encryption failed: {result.stderr}")
                return False, result.stderr
                
        except subprocess.TimeoutExpired:
            return False, "Encryption timed out (disk may be too large)"
        except Exception as e:
            self.logger.error(f"Encryption error: {e}")
            return False, str(e)
        finally:
            # Always clean up temp file
            if 'temp_key_file' in locals() and os.path.exists(temp_key_file):
                os.remove(temp_key_file)
    
    def decrypt_disk(self, disk_path: str, passphrase: str) -> Tuple[bool, str]:
        """
        REAL: Decrypt a LUKS disk using qemu-img convert.
        
        Args:
            disk_path: Path to the encrypted disk
            passphrase: Encryption passphrase
            
        Returns:
            Tuple of (success, decrypted_path or error message)
        """
        if not os.path.exists(disk_path):
            return False, f"Encrypted disk not found: {disk_path}"
        
        # Verify it's actually encrypted
        is_encrypted, _ = self._check_disk_encryption_real(disk_path)
        if not is_encrypted:
            return False, "Disk is not encrypted"
        
        # Generate decrypted disk path
        decrypted_path = disk_path.replace('_encrypted.qcow2', '_decrypted.qcow2')
        if decrypted_path == disk_path:
            decrypted_path = disk_path.replace('.qcow2', '_decrypted.qcow2')
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.key') as f:
                f.write(passphrase)
                temp_key_file = f.name
            os.chmod(temp_key_file, 0o600)
            
            # Build qemu-img convert command for decryption
            cmd = [
                'qemu-img', 'convert',
                '-f', 'qcow2',
                '-O', 'qcow2',
                '--object', f'secret,id=sec0,file={temp_key_file}',
                '--image-opts',
                f'driver=qcow2,file.driver=file,file.filename={disk_path},encrypt.key-secret=sec0',
                decrypted_path
            ]
            
            self.logger.info(f"Decrypting disk: {disk_path} -> {decrypted_path}")
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            
            if result.returncode == 0:
                self.logger.info(f"Successfully decrypted disk: {decrypted_path}")
                return True, decrypted_path
            else:
                self.logger.error(f"Decryption failed: {result.stderr}")
                return False, result.stderr
                
        except subprocess.TimeoutExpired:
            return False, "Decryption timed out"
        except Exception as e:
            self.logger.error(f"Decryption error: {e}")
            return False, str(e)
        finally:
            if 'temp_key_file' in locals() and os.path.exists(temp_key_file):
                os.remove(temp_key_file)
    
    def verify_passphrase(self, disk_path: str, passphrase: str) -> bool:
        """
        REAL: Verify a passphrase works for an encrypted disk.
        
        Args:
            disk_path: Path to the encrypted disk
            passphrase: Passphrase to verify
            
        Returns:
            True if passphrase is correct, False otherwise
        """
        if not os.path.exists(disk_path):
            return False
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.key') as f:
                f.write(passphrase)
                temp_key_file = f.name
            os.chmod(temp_key_file, 0o600)
            
            # Try to read disk info with the passphrase
            # If the passphrase is wrong, qemu-img will fail
            cmd = [
                'qemu-img', 'info',
                '--object', f'secret,id=sec0,file={temp_key_file}',
                '--image-opts',
                f'driver=qcow2,file.driver=file,file.filename={disk_path},encrypt.key-secret=sec0'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            return result.returncode == 0
            
        except Exception as e:
            self.logger.error(f"Passphrase verification error: {e}")
            return False
        finally:
            if 'temp_key_file' in locals() and os.path.exists(temp_key_file):
                os.remove(temp_key_file)
    
    def change_passphrase(self, disk_path: str, old_passphrase: str, new_passphrase: str) -> bool:
        """
        REAL: Change encryption passphrase for a disk.
        
        Note: qemu-img doesn't support in-place passphrase change.
        We re-encrypt the disk with the new passphrase.
        
        Args:
            disk_path: Path to the encrypted disk
            old_passphrase: Current passphrase
            new_passphrase: New passphrase
            
        Returns:
            True if successful, False otherwise
        """
        # First verify the old passphrase
        if not self.verify_passphrase(disk_path, old_passphrase):
            self.logger.error("Old passphrase is incorrect")
            return False
        
        # Decrypt to temp file
        success, decrypted_or_error = self.decrypt_disk(disk_path, old_passphrase)
        if not success:
            self.logger.error(f"Failed to decrypt: {decrypted_or_error}")
            return False
        
        decrypted_path = decrypted_or_error
        
        try:
            # Backup original
            backup_path = disk_path + '.backup'
            os.rename(disk_path, backup_path)
            
            # Re-encrypt with new passphrase
            config = EncryptionConfig(passphrase=new_passphrase)
            success, encrypted_or_error = self.encrypt_disk(decrypted_path, config)
            
            if success:
                # Move new encrypted disk to original location
                os.rename(encrypted_or_error, disk_path)
                os.remove(backup_path)
                os.remove(decrypted_path)
                self.logger.info("Passphrase changed successfully")
                return True
            else:
                # Restore backup
                os.rename(backup_path, disk_path)
                if os.path.exists(decrypted_path):
                    os.remove(decrypted_path)
                self.logger.error(f"Re-encryption failed: {encrypted_or_error}")
                return False
                
        except Exception as e:
            self.logger.error(f"Passphrase change error: {e}")
            return False


def create_encrypted_disk(path: str, size: str, passphrase: str, 
                          cipher: str = "aes-xts-plain64") -> Tuple[bool, str]:
    """
    Create a new LUKS-encrypted qcow2 disk.
    
    Args:
        path: Path for the new encrypted disk
        size: Disk size (e.g., "50G", "100G")
        passphrase: Encryption passphrase
        cipher: Cipher algorithm
        
    Returns:
        Tuple of (success, path or error message)
    """
    try:
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.key') as f:
            f.write(passphrase)
            temp_key_file = f.name
        os.chmod(temp_key_file, 0o600)
        
        # Create encrypted disk directly
        cmd = [
            'qemu-img', 'create',
            '-f', 'qcow2',
            '-o', 'encrypt.format=luks,encrypt.key-secret=sec0',
            '--object', f'secret,id=sec0,file={temp_key_file}',
            path, size
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode == 0:
            return True, path
        else:
            return False, result.stderr
            
    except Exception as e:
        return False, str(e)
    finally:
        if 'temp_key_file' in locals() and os.path.exists(temp_key_file):
            os.remove(temp_key_file)