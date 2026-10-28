import QtQuick
import qs.Common
import qs.DCommon.Widgets
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
    implicitWidth: vertical ? Math.max(28, values.implicitWidth) : bars.width + Theme.spacingS + values.implicitWidth
    implicitHeight: vertical ? bars.height + Theme.spacingXS + values.implicitHeight : Math.max(bars.height, values.implicitHeight)
    Accessible.name: "Subscription Usage Meter"
    Accessible.description: detail(codex, "Codex") + "; " + detail(claude, "Claude") + ". Each column is one subscription's own quota, not a shared total."

    function detail(account, name) {
        var primary = Usage.barWindow(account);
        if (!primary) return name + ": " + (account.status === "auth" ? "sign-in needed" : "not connected");
        return name + ": " + Usage.percent(primary) + " used · " + primary.label + (root.failed || account.status === "stale" ? " (saved usage)" : "");
    }

    Row {
        id: bars
        objectName: "usageBars"
        x: root.vertical ? (root.width - width) / 2 : 0
        y: root.vertical ? 0 : (root.height - height) / 2
        height: Theme.spacingL
        spacing: Theme.spacingXXS
        Repeater {
            model: root.meters
            Rectangle {
                id: barTrack
                required property var modelData
                readonly property var window: Usage.barWindow(modelData)
                readonly property bool known: window && typeof window.used === "number" && isFinite(window.used)
                objectName: "usageBar-" + modelData.provider
                width: Theme.spacingXS
                height: bars.height
                radius: Theme.cornerRadiusXXS
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
            width: Theme.spacingXS
            height: bars.height
            radius: Theme.cornerRadiusXXS
            color: Theme.withAlpha(Theme.surfaceText, 0.12)
        }
    }
    Grid {
        id: values
        x: root.vertical ? (root.width - width) / 2 : bars.width + Theme.spacingS
        y: root.vertical ? bars.height + Theme.spacingXS : (root.height - height) / 2
        columns: root.vertical ? 1 : Math.max(1, root.meters.length)
        columnSpacing: Theme.spacingS
        rowSpacing: Theme.spacingXXS
        Repeater {
            model: root.meters
            Row {
                id: meter
                required property var modelData
                readonly property color accent: Usage.accentText(modelData.provider, Theme.isLightMode)
                readonly property bool overPace: root.showPacing && !root.failed && Usage.overPace(modelData, root.now)
                spacing: 0
                LayoutMirroring.enabled: root.vertical
                opacity: root.failed || modelData.status === "stale" ? 0.55 : 1
                DIcon {
                    objectName: "paceArrow-" + meter.modelData.provider
                    visible: meter.overPace
                    anchors.verticalCenter: parent.verticalCenter
                    name: "arrow_upward"
                    size: root.vertical ? 11 : 13
                    color: meter.accent
                }
                StyledText {
                    objectName: "barPercent-" + meter.modelData.provider
                    text: Usage.percent(Usage.barWindow(meter.modelData))
                    color: meter.accent
                    font.pixelSize: Theme.fontSizeSmall
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
