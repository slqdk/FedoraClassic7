// Network icon in the tray: the Classic 7 one (IP shown at once) instead of Plasma's.
// Plasma's stays "known" so the tray doesn't add it back by itself.
function classic7Tray(tray) {
    if (!tray) return;
    tray.currentConfigGroup = [];
    var id = tray.readConfig("SystrayContainmentId");
    var c = id ? desktopById(id) : null;
    if (!c) return;
    var nm = "org.kde.plasma.networkmanagement", ours = "org.classic7.network";
    // Plasma's icon may already be running in the tray: remove it, not only from the list
    c.widgets(nm).forEach(function (w) { w.remove(); });
    c.currentConfigGroup = ["General"];
    function list(k) {
        var v = c.readConfig(k, []);
        if (typeof v === "string") v = v ? v.split(",") : [];
        return v;
    }
    var extra = list("extraItems").filter(function (x) { return x !== nm; });
    var known = list("knownItems");
    [nm, ours].forEach(function (x) { if (known.indexOf(x) === -1) known.push(x); });
    if (extra.indexOf(ours) === -1) extra.push(ours);
    c.writeConfig("extraItems", extra);
    c.writeConfig("knownItems", known);
    c.reloadConfig();
}
