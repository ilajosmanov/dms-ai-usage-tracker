import QtQuick
import Quickshell
import Quickshell.Io
import qs.Common
import qs.Modules.Plugins
import "Usage.js" as Usage

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
    readonly property int collectionInterval: Usage.refreshIntervalMs(pluginData.refreshInterval)
    readonly property string scriptPath: decodeURIComponent(Qt.resolvedUrl("get-ai-usage").toString().replace(/^file:\/\//, ""))

    function refresh(force) {
        if (collector.running) {
            // Preserve manual refresh requests while collection is running.
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
                    // Avoid rebuilding delegates for identical account data.
                    var payload = JSON.stringify(result.accounts);
                    if (payload !== root.lastPayload) {
                        root.lastPayload = payload;
                        root.snapshot = result;
                    }
                    root.now = Date.now();
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
            root.forceRequest = false;
            if (root.queuedForce) {
                root.queuedForce = false;
                queuedRefresh.restart();
            }
        }
    }
    Timer {
        interval: root.collectionInterval
        repeat: true; running: true; triggeredOnStart: true
        onTriggered: root.refresh(false)
    }
    Timer {
        interval: 60000
        repeat: true; running: true
        onTriggered: root.now = Date.now()
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
