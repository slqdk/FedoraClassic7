// Classic 7: the taskbar's right-click menu in the Windows 7 order.
//   Cascade windows / Show windows stacked / Show windows side by side   (classic7-arrange)
//   Show the desktop                                                      (KWin's Show Desktop)
//   Start Task Manager                                                    (classic7-taskmgr)
//   ---
//   Add or Manage Widgets... / Show Panel Configuration ("Properties")   (Plasma's own)
#include <QAction>
#include <QDBusConnection>
#include <QDBusMessage>
#include <QIcon>
#include <QProcess>

#include <KPluginFactory>
#include <Plasma/Containment>
#include <plasma/containmentactions.h>

class TaskbarMenu : public Plasma::ContainmentActions
{
    Q_OBJECT
public:
    TaskbarMenu(QObject *parent, const QVariantList &args)
        : Plasma::ContainmentActions(parent, args)
    {
        m_cascade = make(QStringLiteral("Cascade windows"), QStringLiteral("window-duplicate"), [] { arrange(QStringLiteral("cascade")); });
        m_stacked = make(QStringLiteral("Show windows stacked"), QStringLiteral("view-split-top-bottom"), [] { arrange(QStringLiteral("stacked")); });
        m_sideBySide = make(QStringLiteral("Show windows side by side"), QStringLiteral("view-split-left-right"), [] { arrange(QStringLiteral("side")); });
        m_desktop = make(QStringLiteral("Show the desktop"), QStringLiteral("user-desktop"), [] {
            QDBusMessage m = QDBusMessage::createMethodCall(QStringLiteral("org.kde.kglobalaccel"), QStringLiteral("/component/kwin"),
                                                            QStringLiteral("org.kde.kglobalaccel.Component"), QStringLiteral("invokeShortcut"));
            m << QStringLiteral("Show Desktop");
            QDBusConnection::sessionBus().asyncCall(m);
        });
        m_taskManager = make(QStringLiteral("Start Task Manager"), QStringLiteral("utilities-system-monitor"), [] {
            QProcess::startDetached(QStringLiteral("classic7-taskmgr"), {});
        });
        m_sep1 = new QAction(this);
        m_sep1->setSeparator(true);
        m_sep2 = new QAction(this);
        m_sep2->setSeparator(true);
        m_sep3 = new QAction(this);
        m_sep3->setSeparator(true);
    }

    QList<QAction *> contextualActions() override
    {
        QList<QAction *> out{m_cascade, m_stacked, m_sideBySide, m_sep1, m_desktop, m_sep2, m_taskManager, m_sep3};
        if (Plasma::Containment *c = containment()) {
            for (const QString &name : {QStringLiteral("add widgets"), QStringLiteral("configure")}) {
                QAction *a = c->internalAction(name);
                if (a && a->isEnabled() && a->isVisible()) {
                    out << a;
                }
            }
        }
        return out;
    }

private:
    template<typename F>
    QAction *make(const QString &text, const QString &icon, F f)
    {
        auto *a = new QAction(QIcon::fromTheme(icon), text, this);
        connect(a, &QAction::triggered, this, f);
        return a;
    }

    static void arrange(const QString &mode)
    {
        QProcess::startDetached(QStringLiteral("classic7-arrange"), {mode});
    }

    QAction *m_cascade, *m_stacked, *m_sideBySide, *m_desktop, *m_taskManager, *m_sep1, *m_sep2, *m_sep3;
};

K_PLUGIN_CLASS_WITH_JSON(TaskbarMenu, "taskbarmenu.json")

#include "taskbarmenu.moc"
