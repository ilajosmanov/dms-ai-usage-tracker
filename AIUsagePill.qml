import QtQuick
import qs.Common
import qs.Widgets
import "Usage.js" as Usage

Item {
    id: root
    property var snapshot: ({accounts: []})
    property bool failed: false
    property bool vertical: false
    property bool showPacing: true
    property real now: Date.now()
    readonly property var codex: Usage.representativeAccount(Usage.providerAccounts(snapshot, "codex")) || {windows: [], status: "missing"}
    readonly property var claude: Usage.representativeAccount(Usage.providerAccounts(snapshot, "claude")) || {windows: [], status: "missing"}
    readonly property var meters: Usage.barAccounts(codex, claude)
    readonly property int overPaceCount: showPacing && !failed ? meters.filter(function(a) { return Usage.overPace(a, root.now); }).length : 0
    implicitWidth: vertical ? Math.max(28, values.implicitWidth) : bars.width + 7 + values.implicitWidth
    implicitHeight: vertical ? bars.height + 4 + values.implicitHeight : Math.max(bars.height, values.implicitHeight)
    Accessible.name: "AI Usage"
    Accessible.description: detail(codex, "Codex") + "; " + detail(claude, "Claude") + ". Each column is one subscription's own quota, not a shared total."

    function detail(account, name) {
        var primary = (account.windows || [])[0];
        if (!primary) return name + ": " + (account.status === "auth" ? "sign-in needed" : "not connected");
        return name + ": " + Usage.percent(primary) + " used · " + primary.label + (root.failed || account.status === "stale" ? " (saved usage)" : "");
    }

    // Twin verticals: one 4px column per consuming provider, filled from the
    // bottom. Height is the shape of the quota, so the pill reads before the
    // digits do.
    Row {
        id: bars
        objectName: "usageBars"
        x: root.vertical ? (root.width - width) / 2 : 0
        y: root.vertical ? 0 : (root.height - height) / 2
        height: 16
        spacing: 3
        Repeater {
            model: root.meters
            Rectangle {
                id: barTrack
                required property var modelData
                readonly property var window: (modelData.windows || [])[0]
                readonly property bool known: window && typeof window.used === "number" && isFinite(window.used)
                objectName: "usageBar-" + modelData.provider
                width: 4
                height: bars.height
                radius: 2
                color: Theme.withAlpha(Theme.surfaceText, 0.12)
                Rectangle {
                    objectName: "usageBarFill-" + barTrack.modelData.provider
                    anchors.bottom: parent.bottom
                    width: parent.width
                    radius: parent.radius
                    height: !barTrack.known || barTrack.window.used <= 0 ? 0
                        : Math.max(2, parent.height * Math.min(1, barTrack.window.used / 100))
                    color: Usage.accent(barTrack.modelData.provider)
                    opacity: root.failed || barTrack.modelData.status === "stale" ? 0.55 : 1
                }
            }
        }
        Rectangle {
            visible: root.meters.length === 0
            width: 4
            height: bars.height
            radius: 2
            color: Theme.withAlpha(Theme.surfaceText, 0.12)
        }
    }
    Grid {
        id: values
        x: root.vertical ? (root.width - width) / 2 : bars.width + 7
        y: root.vertical ? bars.height + 4 : (root.height - height) / 2
        columns: root.vertical ? 1 : Math.max(1, root.meters.length)
        columnSpacing: 8
        rowSpacing: 2
        Repeater {
            model: root.meters
            Row {
                id: meter
                required property var modelData
                readonly property color accent: Usage.accentText(modelData.provider, Theme.isLightMode)
                readonly property bool overPace: root.showPacing && !root.failed && Usage.overPace(modelData, root.now)
                spacing: 0
                // Stacked in a vertical bar the arrow trails the number, so the
                // digits of both providers still start on the same pixel.
                LayoutMirroring.enabled: root.vertical
                opacity: root.failed || modelData.status === "stale" ? 0.55 : 1
                DankIcon {
                    objectName: "paceArrow-" + meter.modelData.provider
                    visible: meter.overPace
                    anchors.verticalCenter: parent.verticalCenter
                    name: "arrow_upward"
                    size: root.vertical ? 11 : 13
                    color: meter.accent
                }
                StyledText {
                    objectName: "barPercent-" + meter.modelData.provider
                    text: Usage.percent((meter.modelData.windows || [])[0])
                    color: meter.accent
                    font.pixelSize: root.vertical ? Math.round(Theme.fontScale * 11) : Theme.fontSizeSmall
                    font.weight: Font.Medium
                }
            }
        }
        StyledText {
            visible: root.meters.length === 0
            text: "—"
            color: Theme.surfaceVariantText
            font.pixelSize: Theme.fontSizeSmall
        }
    }
}
