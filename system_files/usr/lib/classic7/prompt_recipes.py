"""Built-in task library for Command Prompt: works without the language model.

Each recipe has an English and a Danish title, the command, a one-line explanation and
search words in both languages. `<...>` in a command marks a part you fill in.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Recipe:
    group: str
    title: str
    title_da: str
    command: str
    explanation: str
    keywords: str = ""

    @property
    def needs_input(self) -> bool:
        return "<" in self.command and ">" in self.command


R = Recipe
RECIPES: list[Recipe] = [
    # Updates
    R("Updates", "Update everything (system, apps, firmware)", "Opdater alt (system, programmer, firmware)",
      "classic7-update", "Downloads the newest Classic 7 image plus Flatpak apps; asks to restart.",
      "update upgrade opdater opdatering nyeste version system"),
    R("Updates", "Is there a new Classic 7 version?", "Er der en ny Classic 7-version?",
      "classic7-update --check", "Only checks; downloads nothing.", "check update tjek opdatering ny version"),
    R("Updates", "Show installed and downloaded versions", "Vis installeret og hentet version",
      "classic7-update --status", "The running image and any update waiting for a restart.",
      "version status bootc deployment hvilken version"),
    R("Updates", "Go back to the previous version", "Gå tilbage til forrige version",
      "classic7-update --rollback", "The previous image starts at the next restart.",
      "rollback undo fortryd tilbage forrige version broken"),
    R("Updates", "Update only the Flatpak apps", "Opdater kun Flatpak-programmer",
      "flatpak update -y", "Updates the apps from Flathub.", "flatpak update apps programmer opdater"),
    # Programs
    R("Programs", "Search for a program", "Søg efter et program",
      "flatpak search <name>", "Searches Flathub; the Application ID column is what you install.",
      "search find program app søg find installer"),
    R("Programs", "Install a program from Flathub", "Installer et program fra Flathub",
      "flatpak install -y flathub <application id>", "Example ID: org.videolan.VLC. You can also use the Bazaar app store.",
      "install installer program app flathub vlc gimp discord"),
    R("Programs", "List installed programs", "Vis installerede programmer",
      "flatpak list --app --columns=name,application,version", "All Flatpak apps.",
      "list installed programs installerede programmer apps"),
    R("Programs", "Uninstall a program", "Afinstaller et program",
      "flatpak uninstall <application id>", "Find the ID with the 'list installed programs' task.",
      "uninstall remove afinstaller fjern slet program"),
    R("Programs", "Install a command-line tool (Homebrew)", "Installer et kommandolinjeværktøj (Homebrew)",
      "brew install <tool>", "For tools like htop, btop, ffmpeg, yt-dlp, node.",
      "brew homebrew cli tool værktøj htop btop ffmpeg"),
    R("Programs", "Make an Ubuntu box for .deb software", "Lav en Ubuntu-boks til .deb-programmer",
      "distrobox create -i ubuntu:24.04 -n ubuntu && distrobox enter ubuntu",
      "A full Ubuntu in a container; inside it, sudo apt install works.",
      "distrobox ubuntu deb apt container debian"),
    R("Programs", "Make a Fedora box for dnf/rpm software", "Lav en Fedora-boks til dnf/rpm-programmer",
      "distrobox create -i registry.fedoraproject.org/fedora-toolbox:44 -n fedora && distrobox enter fedora",
      "A normal Fedora where sudo dnf install works.", "distrobox fedora dnf rpm container toolbox"),
    R("Programs", "Add a system package (last resort)", "Tilføj en systempakke (sidste udvej)",
      "rpm-ostree install <package>", "Layers an RPM onto the image; active after a restart. Slows updates.",
      "rpm-ostree layer package pakke system driver"),
    # Disks and files
    R("Disks and files", "How much space is free?", "Hvor meget plads er der fri?",
      "df -h -x tmpfs -x devtmpfs -x efivarfs", "Size, used and free space per drive.",
      "disk space free plads fri harddisk drev df"),
    R("Disks and files", "What uses the most space here?", "Hvad fylder mest her?",
      "du -h --max-depth=1 . 2>/dev/null | sort -h | tail -n 15", "The 15 biggest folders in the current folder.",
      "biggest largest folders fylder mest størrelse du"),
    R("Disks and files", "List drives and partitions", "Vis drev og partitioner",
      "lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINTS", "All disks, USB sticks and partitions.",
      "drives disks partitions usb drev diske lsblk"),
    R("Disks and files", "Find a file by name", "Find en fil ud fra navn",
      "find ~ -iname '*<part of name>*' 2>/dev/null | head -n 50", "Searches your home folder.",
      "find file search søg fil navn"),
    R("Disks and files", "Find text inside files", "Find tekst inde i filer",
      "grep -rIn --color=always '<text>' . | head -n 50", "Searches the current folder and below.",
      "grep search text inside files søg tekst indhold"),
    R("Disks and files", "Mount a USB stick", "Monter en USB-nøgle",
      "udisksctl mount -b /dev/<sdX1>", "Find the name with 'list drives'. It appears under /run/media.",
      "mount usb stick monter nøgle udisksctl"),
    R("Disks and files", "Safely remove a USB stick", "Fjern en USB-nøgle sikkert",
      "udisksctl unmount -b /dev/<sdX1> && udisksctl power-off -b /dev/<sdX>", "Unmounts and powers it off.",
      "eject unmount remove usb skub ud fjern sikkert"),
    # System
    R("System", "System information", "Systeminformation",
      "fastfetch 2>/dev/null || hostnamectl", "CPU, GPU, memory, version.",
      "system info information specs neofetch fastfetch"),
    R("System", "GPU status (RX 7900 XTX)", "GPU-status (RX 7900 XTX)",
      "lact cli info 2>/dev/null || cat /sys/class/drm/card*/device/gpu_busy_percent", "Clock, temperature and load of the graphics card.",
      "gpu graphics card grafikkort temperatur amd radeon lact"),
    R("System", "What uses the CPU and memory?", "Hvad bruger CPU og hukommelse?",
      "htop 2>/dev/null || top", "Live list of programs; q quits.", "cpu memory ram process task manager joblisten htop top"),
    R("System", "Memory usage", "Hukommelsesforbrug", "free -h", "Used and free RAM and swap.", "memory ram hukommelse free"),
    R("System", "Temperatures", "Temperaturer", "sensors", "CPU, GPU and disk temperatures.", "temperature temperatur sensors varme"),
    R("System", "Errors since start", "Fejl siden opstart",
      "journalctl -b -p err --no-pager | tail -n 40", "The last 40 error messages since this boot.",
      "errors log fejl logfil journal journalctl crash"),
    R("System", "Failed services", "Fejlede tjenester", "systemctl --failed",
      "Background services that did not start.", "failed services tjenester fejl systemctl"),
    R("System", "Kernel messages (hardware problems)", "Kernebeskeder (hardwareproblemer)",
      "sudo dmesg --level=err,warn | tail -n 40", "Driver and hardware warnings.", "dmesg kernel hardware driver"),
    # Network
    R("Network", "My IP addresses", "Mine IP-adresser", "ip -brief address",
      "IP address per network card.", "ip address adresse netværk network"),
    R("Network", "Is the internet working?", "Virker internettet?",
      "ping -c 4 1.1.1.1 && ping -c 2 fedoraproject.org", "Tests the connection and name lookup.",
      "internet ping connection forbindelse dns"),
    R("Network", "Wi-Fi networks nearby", "Wi-Fi-netværk i nærheden", "nmcli device wifi list",
      "Networks with signal strength.", "wifi wlan trådløs netværk"),
    R("Network", "Is my local AI server reachable?", "Kan jeg nå min lokale AI-server?",
      "curl -s --max-time 5 <server>/api/tags | head -c 400", "Lists the models on an Ollama server.",
      "ollama ai llm server model"),
    # Games
    R("Games", "Restart Steam", "Genstart Steam",
      "steam -shutdown; sleep 3; steam &>/dev/null & disown", "Closes and starts Steam again.",
      "steam restart genstart games spil"),
    R("Games", "Bazzite tasks (ujust)", "Bazzite-opgaver (ujust)", "ujust --choose",
      "A menu of Bazzite system tasks: Secure Boot key, gaming tweaks and more.", "ujust bazzite tasks opgaver menu"),
    R("Games", "Enroll the Secure Boot key", "Tilmeld Secure Boot-nøglen", "ujust enroll-secure-boot-key",
      "Password at the blue screen after restart: universalblue.", "secure boot mok key nøgle"),
]


STOPWORDS = set("""the and for how what why can are is my me you your with from this that there here
has have not get does show want need is er en et af og to on in at of it my i hvor hvad hvordan hvorfor der det den har jeg min mit mine kan skal
vil til fra med som ikke paa for hvis lige bare gerne vise""".split())


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = text.replace("ø", "o").replace("æ", "ae").replace("å", "a")
    return "".join(c for c in text if not unicodedata.combining(c))


def search(query: str, limit: int = 8) -> list[Recipe]:
    """Rank recipes by how many query words appear in title, keywords and command."""
    words = [w for w in re.findall(r"\w+", _norm(query)) if len(w) > 1 and w not in STOPWORDS]
    if not words:
        return []
    scored = []
    for r in RECIPES:
        hay = _norm(" ".join((r.title, r.title_da, r.keywords, r.command, r.group)))
        score = sum(2 if re.search(r"\b" + re.escape(w), hay) else 0 for w in words)
        score += sum(1 for w in words if len(w) > 3 and w in hay)
        if score:
            scored.append((score, r))
    scored.sort(key=lambda t: -t[0])
    return [r for _, r in scored[:limit]]


def groups() -> dict[str, list[Recipe]]:
    out: dict[str, list[Recipe]] = {}
    for r in RECIPES:
        out.setdefault(r.group, []).append(r)
    return out
