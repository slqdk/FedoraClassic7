// classic7-grab: the whole desktop as raw pixels, for Quick Shot.
// Writes one text line "width height stride format scale" (format = QImage::Format number), then the
// pixel rows, to stdout. KWin answers only because /usr/share/applications/classic7-grab.desktop names
// this program with X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2.
#include <QCoreApplication>
#include <QDBusConnection>
#include <QDBusInterface>
#include <QDBusMessage>
#include <QDBusMetaType>
#include <QDBusUnixFileDescriptor>
#include <QVariantMap>

#include <cstdio>
#include <fcntl.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    int fds[2];
    if (pipe2(fds, O_CLOEXEC) != 0) {
        perror("pipe");
        return 2;
    }
    QDBusInterface iface(QStringLiteral("org.kde.KWin.ScreenShot2"), QStringLiteral("/org/kde/KWin/ScreenShot2"),
                         QStringLiteral("org.kde.KWin.ScreenShot2"), QDBusConnection::sessionBus());
    QVariantMap options{{QStringLiteral("native-resolution"), true},
                        {QStringLiteral("include-cursor"), false},
                        {QStringLiteral("hide-caller-windows"), false}};
    QDBusMessage reply = iface.call(QStringLiteral("CaptureWorkspace"), options,
                                    QVariant::fromValue(QDBusUnixFileDescriptor(fds[1])));
    close(fds[1]);
    if (reply.type() != QDBusMessage::ReplyMessage || reply.arguments().isEmpty()) {
        fprintf(stderr, "classic7-grab: %s\n", qPrintable(reply.errorMessage()));
        return 1;
    }
    const QVariantMap res = qdbus_cast<QVariantMap>(reply.arguments().at(0));
    printf("%u %u %u %u %g\n", res.value(QStringLiteral("width")).toUInt(), res.value(QStringLiteral("height")).toUInt(),
           res.value(QStringLiteral("stride")).toUInt(), res.value(QStringLiteral("format")).toUInt(),
           res.value(QStringLiteral("scale"), 1.0).toDouble());
    fflush(stdout);
    char buf[1 << 16];
    ssize_t n;
    while ((n = read(fds[0], buf, sizeof buf)) > 0) {
        if (fwrite(buf, 1, size_t(n), stdout) != size_t(n)) {
            return 3;
        }
    }
    close(fds[0]);
    return 0;
}
