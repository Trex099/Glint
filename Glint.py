import os
import sys
import time

# Add the 'src' directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from core_utils import clear_screen, print_header, print_info, print_warning, print_error, Style
from linux_vm import linux_vm_menu
from macos_vm import macos_vm_menu

def main_menu():
    while True:
        clear_screen()
        print(f"\n{Style.HEADER}{Style.BOLD}Universal VM Manager{Style.ENDC}\n───────────────────────────────────────────────")
        print(f"{Style.OKBLUE}1.{Style.ENDC} {Style.BOLD}Linux VM Management{Style.ENDC}")
        print(f"{Style.OKCYAN}2.{Style.ENDC} {Style.BOLD}macOS VM Management{Style.ENDC}")
        print(f"{Style.WARNING}3.{Style.ENDC} {Style.BOLD}Exit{Style.ENDC}")
        print("────────────────────────────────────────��──────")
        try:
            choice = input(f"{Style.BOLD}Select an option [1-3]: {Style.ENDC}").strip()
            if choice == "1":
                linux_vm_menu()
            elif choice == "2":
                macos_vm_menu()
            elif choice == "3":
                print_info("Exiting. Goodbye! 👋"); break
            else:
                print_warning("Invalid option.")
                time.sleep(1) # Pause to show the message
        except (KeyboardInterrupt, EOFError):
            print_info("\nExiting. Goodbye! 👋"); break
        except RuntimeError as e:
            if "lost sys.stdin" in str(e):
                print_error("This script is interactive and cannot be run in this environment.")
                break
            else:
                raise e

if __name__ == "__main__":
    main_menu()