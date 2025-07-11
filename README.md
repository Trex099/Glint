<p align="center">
  <img src="https://raw.githubusercontent.com/Trex099/Glint/main/assets/Showcase/LOGO.png" alt="Glint Logo" width="250">
  <h1 align="center">Glint</h1>
  <p align="center">
    <strong>The Universal VM Manager That Just Works.</strong>
    <br />
    Create, manage, and secure macOS, Windows, and Linux VMs with zero fuss.
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-3.x-blue.svg" alt="Python 3.x">
    <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey.svg" alt="Platforms">
    <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT">
    <img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome">
  </p>
</p>

Have you ever spent hours trying to get a macOS VM to boot, only to be met with a black screen and a wall of cryptic errors? Have you ever wished you could just *have* a clean, working Linux or macOS environment without the headache of manual setup, configuration files, and endless forum searches?

**Glint is the answer.**

This isn't just another VM manager. Glint is a smart, user-friendly tool built to do one thing perfectly: get you a powerful, fully functional virtual machine with the least amount of effort. It's for anyone who has ever thought, "This should be easier."

---

## ✨ Core Features

Glint is packed with features designed to make VM management powerful, flexible, and simple.

*   **🚀 Automated Host Setup Wizard:** Takes the guesswork out of GPU passthrough. Glint can automatically configure your host system's bootloader (`grub`) and kernel modules to enable IOMMU (VT-d/AMD-Vi), making passthrough accessible even to beginners.
*   **🔥 macOS Factory Reset:** Go beyond simple identity regeneration. Glint can surgically "factory reset" your macOS VM by deleting all user accounts and data, returning you to the initial Setup Assistant without needing to reinstall the entire OS.
*   **🖥️ HiDPI & Custom Resolution:** Enjoy a native desktop experience. Glint automatically detects your host's screen resolution and allows you to set a custom resolution for your VM, enabling proper HiDPI ("Retina") scaling.
*   **📊 Live VM Dashboard:** The main menu features a dynamic dashboard showing the real-time status (Running/Stopped), OS, and resource allocation (CPU/Memory) of all your VMs at a glance.
*   **🧠 Smart Dependency Management:** Glint's startup sequence features a rich, live-updating terminal UI that automatically detects your Linux distribution (Arch, Debian, Fedora, etc.) and installs all required dependencies, including AUR packages for Arch users.
*   **✅ Zero-Config macOS:** Forget the nightmare of manually configuring OpenCore. Glint handles everything, building a perfectly patched bootloader for your VM every single time.
*   **🍏 iMessage & Apple Services Ready:** Glint automatically generates and injects the necessary serial numbers and hardware IDs, giving you the best chance at compatibility with Apple services out of the box.
*   **🗑️ Disposable & Persistent Architecture:** The core of Glint. Keep your OS installation pristine while having the ability to instantly "nuke" a session, creating a forensically clean machine with a new identity (new serial numbers, UUIDs, MAC addresses) without reinstalling.
*   **🎮 Advanced GPU Passthrough (Linux & macOS):** Dedicate a GPU, USB controller, or NVMe drive to your VM for near-native performance. Glint automates the entire process, from host preparation to guest configuration.
*   **📂 Integrated File Transfer:** Easily copy files and folders to and from any running VM using an integrated SFTP/SCP menu, with port forwarding handled automatically.
*   **💿 Intelligent Installer Handling:** Glint automatically detects the OS type of `.iso` files and can convert `.dmg` installers to a bootable format on the fly. It also includes a script to fetch macOS recovery images directly from Apple's servers.

---

## 🖼️ A Glimpse of Glint

Glint's interface is designed to be simple, clean, and intuitive. The main menu greets you with a **Live VM Dashboard**, giving you an immediate overview of all your virtual machines, their status, and their resource allocation. From there, clear and concise menus guide you through every action, from creating a new VM to running the automated Host Setup Wizard for GPU passthrough.

---

## 🚀 How It Works: The "Nuke" Button & The Factory Reset

Glint introduces a new way to think about virtualization. The "Nuke" menu provides two powerful and distinct options for resetting your VM, ensuring you never have to reinstall the operating system.

### ✅ Safe & Non-Destructive by Design

It is critical to understand one thing: **these commands will NEVER delete your base operating system installation.** The `macOS.qcow2` or `base.qcow2` files that hold your OS are never touched.

| Option | What Gets DELETED (The Disposable Part) | What is ALWAYS KEPT (The Persistent Part) | Use Case |
| :--- | :--- | :--- | :--- |
| **Regenerate Identity** | `OpenCore.qcow2` (Bootloader & Identity) | `macOS.qcow2` (Your OS Installation) | Fix iMessage/iCloud issues. |
| **Factory Reset** | All user data inside `macOS.qcow2` | The core macOS system files | Start fresh with a clean user account. |

#### For macOS: A New Mac, Every Time

When you **Regenerate Identity**, you are creating what is, for all intents and purposes, a **brand-new computer** that boots from your existing installation. Glint automatically generates a new SMBIOS, a new MAC address, and rebuilds the bootloader. In seconds, you have a VM that appears to Apple's servers as a completely different machine.

When you perform a **Factory Reset**, Glint mounts the main `macOS.qcow2` disk and surgically deletes all user accounts and their home folders. The next time you boot, you are greeted by the macOS Setup Assistant to create a new user, all while preserving your base OS installation.

---

## 🛠️ Getting Started

### 1. Prerequisites

*   **Operating System:** A modern Linux distribution (Arch, Debian, Ubuntu, Fedora, etc.).
*   **Required Software:** `git` and `python3`.

### 2. Clone the Repository

```bash
git clone https://github.com/Trex099/Glint.git
cd Glint
```

### 3. Place Installers

For the "Create VM" options to work, you **must** place your OS installer files in the `Glint` directory:
*   **macOS:** A full installer `.iso` or a `BaseSystem.dmg`/`.img` file.
*   **Windows:** An `.iso` file. A `virtio-win-*.iso` file is also highly recommended.
*   **Linux:** A standard `.iso` file.

### 4. Run Glint

That's it. The script handles the rest.

```bash
python3 glint.py
```

When you run Glint for the first time, its **Smart Dependency Manager** will:
1.  Detect your Linux distribution.
2.  Check for all required dependencies (like QEMU, OVMF, and `guestfs-tools`).
3.  If anything is missing, it will provide you with the exact command to install it and offer to run it for you.

*Note: The script will use `sudo` internally for operations that require root privileges.*

---

## ⚡ Advanced Features

### 🖥️ GPU Passthrough Made Easy

This feature allows you to give a VM direct control over one of your host's physical GPUs.

#### Host Setup Wizard
Forget editing kernel parameters and bootloader configs. Glint's **Host Setup Wizard** automates the entire host preparation process. It will:
1.  Analyze your system for IOMMU (VT-d/AMD-Vi) readiness.
2.  Automatically add the required kernel parameters to your GRUB configuration.
3.  Configure VFIO modules to load on boot.
4.  Update your `initramfs` and `grub.cfg` to apply the changes.

#### iGPU Framebuffer Patching
For macOS VMs, passing through an Intel iGPU requires special configuration. Glint simplifies this by providing a menu of compatible profiles. Select your iGPU, and Glint will automatically apply the correct framebuffer patches to the OpenCore configuration to enable full graphics acceleration.

#### Reverting Passthrough
If you no longer wish to use GPU passthrough for a VM, a dedicated menu option allows you to safely revert the VM's configuration back to standard virtual graphics.

### 📂 File Transfer (SFTP)

Glint includes a simple menu to transfer large files or directories to and from any running VM.

**How to use it:**
1.  **Enable SSH in the Guest VM (One-time setup):**
    *   **macOS:** Open the Terminal app inside your macOS VM and run:
        ```sh
        sudo systemsetup -setremotelogin on
        ```
    *   **Linux:** Install the OpenSSH server (e.g., `sudo apt install openssh-server` or `sudo pacman -S openssh`) and ensure the `sshd` service is running.
    *   **Windows:** Enable the OpenSSH Server optional feature.
2.  From the appropriate VM menu in Glint, select `Transfer Files (SFTP)`.
3.  Follow the prompts to enter your VM's username, password, and the file paths.

---

## ❤️ Credits and Acknowledgements

This project stands on the shoulders of giants. Glint wouldn't be possible without the incredible work of the open-source community.

*   **QEMU:** For providing the powerful, flexible, and open-source virtualization engine that makes all of this possible.
*   **OpenCore:** For their sophisticated bootloader that allows us to boot macOS on non-Apple hardware.
*   **OSX-KVM:** For providing invaluable references and a solid foundation for macOS virtualization on Linux.
*   **GenSMBIOS:** For the essential tool that makes generating valid SMBIOS information a breeze.

---

## ⚖️ Legality of macOS on Non-Apple Hardware

While this project provides the technical means to install macOS in a virtual machine on non-Apple hardware, it is important to understand the legal and ethical implications. Apple's End User License Agreement (EULA) for macOS states that the operating system is only to be installed on Apple-branded hardware.

From the macOS Sonoma EULA:
> "...you are granted a limited, non-transferable, non-exclusive license... to install, use and run one (1) copy of the Apple Software on a single Apple-branded computer at any one time."

By using this tool to install macOS on a non-Apple system, you are acting in violation of this EULA. This project is provided for educational and research purposes only. The developers of Glint are not responsible for your use of this software, and you assume all responsibility for complying with Apple's licensing terms.

We do not provide support for and are not responsible for any legal issues that may arise from your use of this project. We encourage all users to respect the licensing of the software they use.

---

## 🔮 Upcoming Features

Glint is an actively developed project. Here's what we have planned for the future:

*   **Snapshot Management:** The ability to take and restore snapshots of your persistent VM states.
*   **GUI Frontend:** A simple graphical user interface for users who prefer a visual workflow.

---

## ❤️ Contributing

We welcome contributions from the community! If you have an idea for a new feature, a bug fix, or an improvement to the documentation, please feel free to open an issue or submit a pull request.

---

## 📜 License

This project is licensed under the MIT License. See the `LICENSE` file for details.
