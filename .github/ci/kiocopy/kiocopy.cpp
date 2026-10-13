// kiocopy SOURCE... DESTINATION: copies like Dolphin does (KIO::copy with progress reporting), so
// the job goes to the session's job view server (Classic 7's copy window)
#include <QApplication>
#include <QUrl>

#include <KIO/CopyJob>
#include <KIO/JobUiDelegateFactory>

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    // the job view server is only told about jobs of programs with a desktop file name (as Dolphin)
    app.setDesktopFileName(QStringLiteral("org.kde.dolphin"));
    if (argc < 3) {
        return 2;
    }
    QList<QUrl> sources;
    for (int i = 1; i < argc - 1; ++i) {
        sources << QUrl::fromLocalFile(QString::fromLocal8Bit(argv[i]));
    }
    KIO::CopyJob *job = KIO::copy(sources, QUrl::fromLocalFile(QString::fromLocal8Bit(argv[argc - 1])));
    job->setUiDelegate(KIO::createDefaultJobUiDelegate());
    QObject::connect(job, &KJob::result, &app, [&app](KJob *j) {
        app.exit(j->error());
    });
    return app.exec();
}
