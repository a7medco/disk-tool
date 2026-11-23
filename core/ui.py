"""Terminal UI helpers: colors, numbered menus, safe confirmations."""
import sys

_TTY = sys.stdout.isatty()

# Enable ANSI colours in the Windows console (Win10+)
if sys.platform == "win32":
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetConsoleMode(k.GetStdHandle(-11), 7)
    except Exception:
        _TTY = False
RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
RED, GREEN, YELLOW, CYAN = "\033[31m", "\033[32m", "\033[33m", "\033[36m"


def c(text, color):
    return (color + str(text) + RESET) if _TTY else str(text)


def header(title):
    line = "=" * max(40, len(title) + 4)
    print("\n" + c(line, CYAN))
    print(c("  " + title, BOLD))
    print(c(line, CYAN))


def info(msg):
    print(c("[i] ", CYAN) + msg)


def ok(msg):
    print(c("[OK] ", GREEN) + msg)


def warn(msg):
    print(c("[!] ", YELLOW) + msg)


def err(msg):
    print(c("[X] ", RED) + msg)


def ask(prompt, default=None):
    """Read a line from the user. Returns default (or '') on empty input / EOF."""
    suffix = " [%s]" % default if default not in (None, "") else ""
    try:
        val = input(c("> ", CYAN) + prompt + suffix + ": ").strip()
    except EOFError:
        print()
        return default or ""
    return val if val else (default or "")


def choose(title, options, back_label="Back"):
    """Show a numbered menu. Returns the chosen index (0-based) or None for Back."""
    if title:
        print("\n" + c(title, BOLD))
    for i, opt in enumerate(options, 1):
        print("  %s %s" % (c("%2d)" % i, YELLOW), opt))
    print("  %s %s" % (c(" 0)", YELLOW), back_label))
    while True:
        val = ask("Choose a number")
        if val == "0" or val.lower() in ("q", "b"):
            return None
        if val.isdigit() and 1 <= int(val) <= len(options):
            return int(val) - 1
        warn("Invalid choice, try again.")


def yes_no(question, default=False):
    d = "Y/n" if default else "y/N"
    val = ask("%s (%s)" % (question, d)).lower()
    if not val:
        return default
    return val in ("y", "yes")


def confirm_typed(expected, what):
    """Destructive-operation guard: the user must type `expected` exactly."""
    print()
    print(c("!!! WARNING: ALL DATA ON %s WILL BE DESTROYED !!!" % what, RED + BOLD))
    val = ask("Type %s to confirm, anything else cancels" % c(expected, BOLD))
    if val == expected:
        return True
    info("Cancelled. Nothing was changed.")
    return False


def pause():
    try:
        input(c("\nPress Enter to continue...", DIM))
    except EOFError:
        pass


def human_size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return ("%.0f %s" if unit == "B" else "%.1f %s") % (n, unit)
        n /= 1000.0


def clean_path(raw):
    """Clean a path typed or drag-and-dropped into Terminal."""
    p = raw.strip()
    if len(p) >= 2 and p[0] == p[-1] and p[0] in ("'", '"'):
        p = p[1:-1]
    return p.replace("\\ ", " ").replace("\\(", "(").replace("\\)", ")").replace("\\&", "&")
