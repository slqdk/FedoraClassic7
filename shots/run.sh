set -x
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick >/dev/null 2>&1 || true
cat > /tmp/combo.py <<'PY'
import sys, gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib
w = Gtk.Window(title="Initialize Waydroid"); w.set_default_size(700, 300)
g = Gtk.Grid(row_spacing=8, column_spacing=40, margin=30); w.add(g)
for i, t in enumerate(("System OTA", "Vendor OTA")):
    g.attach(Gtk.Label(label=t), 0, i, 1, 1); e = Gtk.Entry(); e.set_hexpand(True); g.attach(e, 1, i, 1, 1)
g.attach(Gtk.Label(label="Android Type"), 0, 2, 1, 1)
c = Gtk.ComboBoxText(); [c.append_text(x) for x in ("VANILLA", "GAPPS")]
if sys.argv[1] == "active": c.set_active(0)
g.attach(c, 1, 2, 1, 1); g.attach(Gtk.Button(label="Download"), 1, 3, 1, 1)
w.connect("destroy", Gtk.main_quit); w.show_all()
GLib.timeout_add(1500, lambda: (c.popup(), False)[1])
GLib.timeout_add(9000, Gtk.main_quit); GLib.timeout_add(15000, lambda: sys.exit(0))
Gtk.main()
PY
export GTK_THEME=Classic7
shot_x11() {   # name, combo mode
  DISPLAY=:99 python3 /tmp/combo.py $2 & p=$!; sleep 4; DISPLAY=:99 import -window root /out/$1.png; wait $p
}
shot_wl() {
  WAYLAND_DISPLAY=wl-test GDK_BACKEND=wayland python3 /tmp/combo.py $2 & p=$!; sleep 4
  WAYLAND_DISPLAY=wl-test QT_QPA_PLATFORM=wayland timeout 20 spectacle -b -n -f -o /out/$1.png >/dev/null 2>&1 || true; wait $p
}
cat > /tmp/inner.sh <<'EOI'
export HOME=/tmp/home XDG_RUNTIME_DIR=/tmp/xdg; mkdir -p $HOME $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
Xvfb :99 -screen 0 800x400x24 >/dev/null 2>&1 & sleep 2
kwin_wayland --virtual --width 800 --height 400 --socket wl-test > /out/kwin.log 2>&1 & sleep 5
source /tmp/funcs.sh
shot_x11 x11-before none; shot_x11 x11-before-active active
shot_wl  wayland-before none; shot_wl wayland-before-active active
cat >> /usr/share/themes/Classic7/gtk-3.0/gtk-combobox.css <<'CSS'
combobox { -GtkComboBox-appears-as-list: true; }
combobox window scrolledwindow, combobox window treeview { background-color: @bg_bright; }
combobox window treeview:selected { background-color: @selected_bg_color; color: @selected_fg_color; }
CSS
shot_x11 x11-after none; shot_x11 x11-after-active active
shot_wl  wayland-after none; shot_wl wayland-after-active active
EOI
declare -f shot_x11 shot_wl > /tmp/funcs.sh; echo 'export GTK_THEME=Classic7' >> /tmp/funcs.sh
mkdir -p /out && chmod 777 /out
dbus-run-session -- bash /tmp/inner.sh
