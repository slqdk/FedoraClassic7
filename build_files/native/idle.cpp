// classic7-idle SECONDS: prints "idle" when nobody has used the mouse or keyboard for SECONDS, and
// "resume" when they do again. KIdleTime does the platform work (ext-idle-notify on Wayland), and
// programs that keep the screen on (video, games) hold it off. Used by classic7-screensaver.
#include <KIdleTime>
#include <QGuiApplication>

#include <algorithm>
#include <cstdio>
#include <cstdlib>

int main(int argc, char **argv)
{
    QGuiApplication app(argc, argv);
    const int seconds = argc > 1 ? std::max(5, std::atoi(argv[1])) : 600;
    KIdleTime *idle = KIdleTime::instance();
    QObject::connect(idle, &KIdleTime::timeoutReached, &app, [idle](int, int) {
        std::printf("idle\n");
        std::fflush(stdout);
        idle->catchNextResumeEvent();
    });
    QObject::connect(idle, &KIdleTime::resumingFromIdle, &app, [] {
        std::printf("resume\n");
        std::fflush(stdout);
    });
    idle->addIdleTimeout(seconds * 1000);
    std::printf("ready\n");
    std::fflush(stdout);
    return app.exec();
}
