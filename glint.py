"""
Main entry point for the Universal VM Manager.

This script provides a command-line interface for managing virtual machines.
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from core_utils import clear_screen, print_info, print_warning, print_error, Style, download_file
from linux_vm import linux_vm_menu
from macos_vm import macos_vm_menu
from windows_vm import windows_vm_menu

def check_dependencies():
    """
    Checks for required dependencies and prompts the user to download them if they are missing.
    """
    if not any("virtio" in f.lower() and f.endswith(".iso") for f in os.listdir()):
        print_warning("VirtIO drivers ISO not found.")
        if input("Download it now? (y/N): ").strip().lower() == 'y':
            download_file("https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso", "virtio-win.iso")

def main_menu():
    """
    Displays the main menu and handles user input.
    """
    check_dependencies()
    while True:
        clear_screen()
        print(f"\n{Style.HEADER}{Style.BOLD}Universal VM Manager{Style.ENDC}\n"
              "───────────────────────────────────────────────")
        print(f"{Style.OKBLUE}1.{Style.ENDC} {Style.BOLD}Linux VM Management{Style.ENDC}")
        print(f"{Style.OKCYAN}2.{Style.ENDC} {Style.BOLD}macOS VM Management{Style.ENDC}")
        print(f"{Style.OKGREEN}3.{Style.ENDC} {Style.BOLD}Windows VM Management{Style.ENDC}")
        print(f"{Style.WARNING}4.{Style.ENDC} {Style.BOLD}Exit{Style.ENDC}")
        print("──────────────────────────────────────────────")
        try:
            choice = input(f"{Style.BOLD}Select an option [1-4]: {Style.ENDC}").strip()
            if choice == "1":
                linux_vm_menu()
            elif choice == "2":
                macos_vm_menu()
            elif choice == "3":
                windows_vm_menu()
            elif choice == "4":
                print_info("Exiting. Goodbye! 👋")
                break
            else:
                print_warning("Invalid option.")
                time.sleep(1)  # Pause to show the message
        except (KeyboardInterrupt, EOFError):
            print_info("\nExiting. Goodbye! 👋")
            break
        except RuntimeError as e:
            if "lost sys.stdin" in str(e):
                print_error("This script is interactive and cannot be run in this environment.")
                break
            raise e

if __name__ == "__main__":
    main_menu()
