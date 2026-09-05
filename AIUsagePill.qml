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
    implicitWidth: vertical ? Math.max(28, values.implicitWidth) : ring.width + 7 + values.implicitWidth
    implicitHeight: vertical ? ring.height + 4 + values.implicitHeight : Math.max(ring.height, values.implicitHeight)
    Accessible.name: "AI Usage"
    Accessible.description: detail(codex, "Codex") + "; " + detail(claude, "Claude") + ". Ring shows relative quota percentages, not token totals."

    function detail(account, name) {
        var primary = (account.windows || [])[0];
        if (!primary) return name + ": " + (account.status === "auth" ? "sign-in needed" : "not connected");
        return name + ": " + Usage.percent(primary) + " used · " + primary.label + (root.failed || account.status === "stale" ? " (saved usage)" : "");
    }
    SegmentedRing {
        id: ring
        x: root.vertical ? (root.width - width) / 2 : 0
        y: root.vertical ? 0 : (root.height - height) / 2
        width: 26; height: 26
        codex: root.codex
        claude: root.claude
        failed: root.failed
    }
    Grid {
        id: values
        x: root.vertical ? (root.width - width) / 2 : ring.width + 7
        y: root.vertical ? ring.height + 4 : (root.height - height) / 2
        columns: root.vertical ? 1 : Math.max(1, root.meters.length)
        columnSpacing: 8
        rowSpacing: 2
        Repeater {
            model: root.meters
            Row {
                id: meter
                required property var modelData
                readonly property color accent: Usage.accent(modelData.provider)
                readonly property bool overPace: root.showPacing && !root.failed && Usage.overPace(modelData, root.now)
                spacing: 1
                opacity: root.failed || modelData.status === "stale" ? 0.55 : 1
                DankIcon {
                    objectName: "paceArrow-" + meter.modelData.provider
                    visible: meter.overPace
                    anchors.verticalCenter: parent.verticalCenter
                    name: "arrow_upward"
                    size: root.vertical ? 12 : 16
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
