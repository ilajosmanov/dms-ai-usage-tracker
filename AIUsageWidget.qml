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
    property string selectedProvider: pluginData.defaultProvider === "claude" ? "claude" : "codex"
    property real now: Date.now()
    property bool forceRequest: false
    property bool queuedManualRefresh: false
    readonly property string scriptPath: decodeURIComponent(Qt.resolvedUrl("get-ai-usage").toString().replace(/^file:\/\//, ""))

    function refresh(force) {
        if (collector.running) {
            if (force) queuedManualRefresh = true;
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
            if (root.queuedManualRefresh) {
                root.queuedManualRefresh = false;
                Qt.callLater(() => root.refresh(true));
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
            provider: root.selectedProvider
            loading: collector.running && (root.forceRequest || root.snapshot.accounts.length === 0)
            collectorError: root.collectorError
            now: root.now
            showPacing: root.pluginData.showPacing !== false
            maxBodyHeight: root.parentScreen ? Math.max(220, root.parentScreen.height - 160) : 1000
            onRefreshRequested: root.refresh(true)
            onDashboardRequested: url => Qt.openUrlExternally(url)
            onProviderSelected: provider => root.selectedProvider = provider
        }
    }
}
