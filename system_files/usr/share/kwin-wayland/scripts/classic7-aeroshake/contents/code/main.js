// Classic 7: Windows 7 window behaviour that KWin doesn't have by itself.
//  - Aero Shake: grab a window by its title bar and shake it to minimize every other window
//    on that screen; shake it again to bring them back. Win+Home does the same.
//  - Win+Up maximizes (never restores), Win+Down restores a maximized window, else minimizes.
// SPDX-License-Identifier: GPL-2.0-or-later

const SHAKE_DISTANCE = 24;     // pixels a window must travel before it counts as a turn
const SHAKE_TURNS = 3;         // turns needed ...
const SHAKE_TIME = 1000;       // ... within this many milliseconds

let shookBy = null;
let shookAway = [];

function isOnCurrentDesktop(w) {
    if (w.onAllDesktops) {
        return true;
    }
    return (w.desktops || []).indexOf(workspace.currentDesktop) !== -1;
}

function candidates(w) {
    return workspace.windowList().filter(function (o) {
        return o !== w && o.normalWindow && !o.skipTaskbar && !o.minimized && o.minimizable
            && isOnCurrentDesktop(o) && o.output === w.output;
    });
}

function shake(w) {
    if (!w) {
        return;
    }
    if (shookBy === w && shookAway.length > 0) {
        shookAway.forEach(function (o) {
            if (o && o.minimized) {
                o.minimized = false;
            }
        });
        shookAway = [];
        shookBy = null;
        workspace.activeWindow = w;
        return;
    }
    shookAway = candidates(w);
    shookBy = w;
    shookAway.forEach(function (o) { o.minimized = true; });
    workspace.activeWindow = w;
}

function watch(w) {
    if (!w || !w.normalWindow) {
        return;
    }
    let state = null;
    w.interactiveMoveResizeStarted.connect(function () {
        state = { ext: null, dir: 0, turns: [] };
    });
    w.interactiveMoveResizeFinished.connect(function () {
        state = null;
    });
    w.interactiveMoveResizeStepped.connect(function (geometry) {
        if (!state || !w.move) {
            return;           // resizing, not moving
        }
        const x = geometry.x;
        const now = Date.now();
        if (state.ext === null) {
            state.ext = x;
            return;
        }
        const d = x - state.ext;
        if (state.dir === 0) {
            if (Math.abs(d) >= SHAKE_DISTANCE) {
                state.dir = d > 0 ? 1 : -1;
                state.ext = x;
            }
            return;
        }
        if (d * state.dir > 0) {
            state.ext = x;        // still going the same way: the turning point moves along
            return;
        }
        if (Math.abs(d) >= SHAKE_DISTANCE) {
            state.dir = -state.dir;
            state.ext = x;
            state.turns.push(now);
            state.turns = state.turns.filter(function (t) { return now - t < SHAKE_TIME; });
            if (state.turns.length >= SHAKE_TURNS) {
                state.turns = [];
                shake(w);
            }
        }
    });
}

function isMaximized(w) {
    const area = workspace.clientArea(KWin.MaximizeArea, w);
    const g = w.frameGeometry;
    return Math.abs(g.x - area.x) < 2 && Math.abs(g.y - area.y) < 2
        && Math.abs(g.width - area.width) < 2 && Math.abs(g.height - area.height) < 2;
}

workspace.windowList().forEach(watch);
workspace.windowAdded.connect(watch);

registerShortcut("Classic7 Aero Shake", "Classic 7: Minimize all other windows (Aero Shake)", "Meta+Home",
                 function () { shake(workspace.activeWindow); });
registerShortcut("Classic7 Maximize", "Classic 7: Maximize the window (Win+Up)", "",
                 function () {
                     const w = workspace.activeWindow;
                     if (w && w.maximizable) {
                         w.setMaximize(true, true);
                     }
                 });
registerShortcut("Classic7 Restore or Minimize", "Classic 7: Restore, or minimize (Win+Down)", "",
                 function () {
                     const w = workspace.activeWindow;
                     if (!w) {
                         return;
                     }
                     if (w.maximizable && isMaximized(w)) {
                         w.setMaximize(false, false);
                     } else if (w.minimizable) {
                         w.minimized = true;
                     }
                 });
