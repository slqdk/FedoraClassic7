// Classic 7: Explorer's and the desktop's "Properties" open the Windows 7 style window.
// KDE builds its Properties dialog for one item from plugins (kf6/propertiesdialog); this plugin
// keeps that dialog off the screen, closes it, and starts classic7-properties for the item instead,
// with an activation token so the new window comes to the front. Several items at once, items
// that aren't on this computer (network, trash:/ listings) and the "Link to..." dialogs of the
// Create New menu stay with KDE's dialog. CLASSIC7_KDE_PROPERTIES=1 turns the plugin off.
#include <QFile>
#include <QFuture>
#include <QGuiApplication>
#include <QProcess>
#include <QTimer>
#include <QWidget>
#include <QWindow>

#include <KPluginFactory>
#include <KPropertiesDialog>
#include <KPropertiesDialogPlugin>
#include <KWaylandExtras>
#include <KWindowSystem>

static const QString s_program = QStringLiteral("/usr/bin/classic7-properties");
static const QString s_appId = QStringLiteral("classic7-properties");

namespace
{
// Starts the program once: with the token when it arrives, without one if it doesn't come
class Launcher : public QObject
{
public:
    explicit Launcher(const QStringList &args)
        : QObject(qApp)
        , m_args(args)
    {
        QTimer::singleShot(1500, this, [this] {
            launch(QString());
        });
    }

    void launch(const QString &token)
    {
        if (m_done) {
            return;
        }
        m_done = true;
        QProcess process;
        process.setProgram(s_program);
        process.setArguments(m_args);
        QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
        env.remove(QStringLiteral("XDG_ACTIVATION_TOKEN"));
        env.remove(QStringLiteral("DESKTOP_STARTUP_ID"));
        if (!token.isEmpty()) {
            env.insert(QStringLiteral("XDG_ACTIVATION_TOKEN"), token);
        }
        process.setProcessEnvironment(env);
        process.startDetached();
        deleteLater();
    }

private:
    QStringList m_args;
    bool m_done = false;
};
}

class Classic7Properties : public KPropertiesDialogPlugin
{
    Q_OBJECT
public:
    Classic7Properties(QObject *parent, const QVariantList &)
        : KPropertiesDialogPlugin(parent)
    {
        KPropertiesDialog *dialog = properties;
        if (!dialog || qEnvironmentVariableIntValue("CLASSIC7_KDE_PROPERTIES") || !QFile::exists(s_program)) {
            return;
        }
        const KFileItemList items = dialog->items();
        if (items.count() != 1 || !dialog->currentDir().isEmpty()) {
            return;
        }
        const QString path = items.first().localPath();
        if (path.isEmpty()) {
            return;
        }
        dialog->setAttribute(Qt::WA_DontShowOnScreen);
        QTimer::singleShot(0, dialog, &KPropertiesDialog::reject);

        auto *launcher = new Launcher({path});
        QWindow *window = nullptr;
        if (QWidget *parentWidget = dialog->parentWidget()) {
            window = parentWidget->window()->windowHandle();
        }
        if (!window) {
            window = QGuiApplication::focusWindow();
        }
        if (window && KWindowSystem::isPlatformWayland()) {
            KWaylandExtras::xdgActivationToken(window, s_appId).then(launcher, [launcher](const QString &token) {
                launcher->launch(token);
            });
        } else {
            launcher->launch(QString());
        }
    }
};

K_PLUGIN_CLASS_WITH_JSON(Classic7Properties, "properties.json")

#include "properties.moc"
