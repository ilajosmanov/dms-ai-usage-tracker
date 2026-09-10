import QtQuick
import Quickshell
import Quickshell.Io
import qs.Common
import qs.Modules.Plugins

PluginComponent {
    id: root
    pluginId: "aiUsage"
    popoutWidth: 424
    property var snapshot: ({accounts: []})
    property string lastPayload: ""
    property string collectorError: ""
    readonly property string primaryProvider: pluginData.defaultProvider === "claude" ? "claude" : "codex"
    property real now: Date.now()
    property bool forceRequest: false
    property bool queuedForce: false
    readonly property string scriptPath: decodeURIComponent(Qt.resolvedUrl("get-ai-usage").toString().replace(/^file:\/\//, ""))

    function refresh(force) {
        if (collector.running) {
            // A click that lands during the 30-second poll used to vanish. Hold it
            // instead: the button has to mean something every time it is pressed.
            queuedForce = queuedForce || force === true;
            return;
        }
        forceRequest = force === true;
        collector.running = true;
    }
    pillRightClickAction: () => root.refresh(true)
    onPluginDataChanged: settingsRefresh.restart()

    Timer {
        id: settingsRefresh
        interval: 750
        onTriggered: root.refresh(false)
    }
    Timer {
        // Runs the held click once the process has actually let go of `running`.
        id: queuedRefresh
        interval: 0
        onTriggered: root.refresh(true)
    }
    Process {
        id: collector
        command: ["python3", root.scriptPath].concat(root.forceRequest ? ["--force"] : [])
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    var result = JSON.parse(text);
                    if (result.version !== 1 || !Array.isArray(result.accounts))
                        throw new Error("schema");
                    // Reassigning an identical snapshot rebuilds every pill delegate,
                    // so compare before publishing; checkedAt alone is not a change.
                    var payload = JSON.stringify(result.accounts);
                    if (payload !== root.lastPayload) {
                        root.lastPayload = payload;
                        root.snapshot = result;
                    }
                    root.collectorError = "";
                } catch (error) {
                    root.collectorError = "Could not read usage data. Check that Python 3 is installed and run get-ai-usage in a terminal.";
                }
            }
        }
        stderr: StdioCollector {}
        onExited: (exitCode, exitStatus) => {
            if (exitCode !== 0)
                root.collectorError = "The usage collector could not finish. Run get-ai-usage in a terminal to check the installation.";
            // One click forces one check; leaving the flag up would have made every
            // background poll a forced one.
            root.forceRequest = false;
            if (root.queuedForce) {
                root.queuedForce = false;
                queuedRefresh.restart();
            }
        }
    }
    Timer {
        // Local credential/cache check only. The collector controls API refresh/backoff.
        // Every tick re-scans local session logs, so keep it coarse; nothing rendered
        // from `now` is finer than a minute.
        interval: 30000
        repeat: true; running: true; triggeredOnStart: true
        onTriggered: {
            root.now = Date.now();
            root.refresh(false);
        }
    }
    horizontalBarPill: Component {
        AIUsagePill {
            snapshot: root.snapshot
            failed: root.collectorError !== ""
            now: root.now
            showPacing: root.pluginData.showPacing !== false
        }
    }
    verticalBarPill: Component {
        AIUsagePill {
            snapshot: root.snapshot
            failed: root.collectorError !== ""
            now: root.now
            showPacing: root.pluginData.showPacing !== false
            vertical: true
        }
    }
    popoutContent: Component {
        UsageDashboard {
            snapshot: root.snapshot
            primaryProvider: root.primaryProvider
            loading: collector.running
            collectorError: root.collectorError
            now: root.now
            showPacing: root.pluginData.showPacing !== false
            maxBodyHeight: root.parentScreen ? Math.max(220, root.parentScreen.height - 160) : 1000
            onRefreshRequested: root.refresh(true)
            onDashboardRequested: url => Qt.openUrlExternally(url)
        }
    }
}
