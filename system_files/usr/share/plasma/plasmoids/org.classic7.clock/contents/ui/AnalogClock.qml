import QtQuick
import org.kde.kirigami as Kirigami

// The round clock face of the Windows 7 date and time popup
Canvas {
    id: face
    property date time: new Date()
    onTimeChanged: requestPaint()
    onWidthChanged: requestPaint()

    onPaint: {
        const ctx = getContext("2d");
        const w = width, h = height, r = Math.min(w, h) / 2 - 2;
        ctx.reset();
        ctx.translate(w / 2, h / 2);
        // rim and face
        let g = ctx.createLinearGradient(0, -r, 0, r);
        g.addColorStop(0, "#9fb3c8");
        g.addColorStop(1, "#4a6178");
        ctx.beginPath();
        ctx.arc(0, 0, r, 0, Math.PI * 2);
        ctx.fillStyle = g;
        ctx.fill();
        g = ctx.createRadialGradient(-r * 0.3, -r * 0.4, r * 0.1, 0, 0, r * 0.92);
        g.addColorStop(0, "#ffffff");
        g.addColorStop(1, "#dfe7ef");
        ctx.beginPath();
        ctx.arc(0, 0, r * 0.9, 0, Math.PI * 2);
        ctx.fillStyle = g;
        ctx.fill();
        // hour and minute marks
        for (let i = 0; i < 60; i++) {
            const a = i * Math.PI / 30;
            const big = i % 5 === 0;
            ctx.beginPath();
            ctx.lineWidth = big ? Math.max(2, r * 0.04) : 1;
            ctx.strokeStyle = big ? "#2b3a4a" : "#8696a6";
            ctx.moveTo(Math.sin(a) * r * (big ? 0.70 : 0.78), -Math.cos(a) * r * (big ? 0.70 : 0.78));
            ctx.lineTo(Math.sin(a) * r * 0.84, -Math.cos(a) * r * 0.84);
            ctx.stroke();
        }
        const t = face.time;
        const s = t.getSeconds(), m = t.getMinutes() + s / 60, hr = (t.getHours() % 12) + m / 60;
        function hand(angle, len, width, color) {
            ctx.beginPath();
            ctx.lineCap = "round";
            ctx.lineWidth = width;
            ctx.strokeStyle = color;
            ctx.moveTo(-Math.sin(angle) * len * 0.15, Math.cos(angle) * len * 0.15);
            ctx.lineTo(Math.sin(angle) * len, -Math.cos(angle) * len);
            ctx.stroke();
        }
        hand(hr * Math.PI / 6, r * 0.48, Math.max(3, r * 0.07), "#1d2833");
        hand(m * Math.PI / 30, r * 0.70, Math.max(2, r * 0.05), "#1d2833");
        hand(s * Math.PI / 30, r * 0.76, 1, "#c42b1c");
        ctx.beginPath();
        ctx.arc(0, 0, Math.max(2, r * 0.05), 0, Math.PI * 2);
        ctx.fillStyle = "#1d2833";
        ctx.fill();
    }
}
