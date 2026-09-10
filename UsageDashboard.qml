import QtQuick
import QtQuick.Controls
import qs.Common
import qs.Widgets
import "Usage.js" as Usage

Column {
    id: root
    property var snapshot: ({accounts: []})
    property string primaryProvider: "codex"
    property bool loading: false
    property string collectorError: ""
    property bool showPacing: true
    property real now: Date.now()
    property real maxBodyHeight: 1000
    property var closePopout: null
    signal refreshRequested()
    signal dashboardRequested(string url)
    // Column order only; both providers are always on screen.
    readonly property var providers: Usage.orderedProviders(primaryProvider)
    readonly property real columnWidth: (width - padding * 2 - columns.spacing) / 2
    padding: 12
    spacing: 12
    width: 424

    Item {
        id: header
        objectName: "usageHeader"
        width: parent.width - root.padding * 2
        height: 26
        StyledText {
            anchors.left: parent.left
            // The actions keep their natural width; the title is what gives way,
            // so a large font scale can never push "Updated" off the header.
            anchors.right: headerActions.left
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            elide: Text.ElideRight
            text: root.snapshot.demo ? "Subscription Usage Meter · Demo" : "Subscription Usage Meter"
            color: Theme.surfaceText
            font.pixelSize: Math.round(Theme.fontScale * 14)
            font.weight: Font.Medium
        }
        Row {
            id: headerActions
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 4
            StyledText {
                objectName: "updatedLabel"
                anchors.verticalCenter: parent.verticalCenter
                rightPadding: 4
                text: root.loading ? "Checking…" : Usage.age(Usage.latestUpdate(root.snapshot), root.now)
                color: Theme.surfaceVariantText
                font.pixelSize: Math.round(Theme.fontScale * 11)
            }
            ToolButton {
                objectName: "refreshButton"
                padding: 0
                width: 24; height: 24
                anchors.verticalCenter: parent.verticalCenter
                enabled: !root.loading
                Accessible.name: "Refresh usage"
                UsageTooltip { visible: parent.hovered; text: "Refresh usage" }
                background: Rectangle { radius: 12; color: parent.hovered ? Theme.surfaceContainerHigh : "transparent" }
                contentItem: DankIcon { name: "refresh"; size: 15; color: root.loading ? Theme.surfaceVariantText : Theme.surfaceText }
                onClicked: root.refreshRequested()
            }
            ToolButton {
                objectName: "closeButton"
                padding: 0
                width: 24; height: 24
                anchors.verticalCenter: parent.verticalCenter
                Accessible.name: "Close usage"
                UsageTooltip { visible: parent.hovered; text: "Close" }
                background: Rectangle { radius: 12; color: parent.hovered ? Theme.surfaceContainerHigh : "transparent" }
                contentItem: DankIcon { name: "close"; size: 15; color: Theme.surfaceText }
                onClicked: { if (root.closePopout) root.closePopout(); }
            }
        }
    }

    Rectangle {
        objectName: "collectorErrorCard"
        width: parent.width - root.padding * 2
        implicitHeight: collectorErrorText.implicitHeight + 20
        radius: Theme.cornerRadius
        color: Theme.surfaceContainerHigh
        visible: root.collectorError !== ""
        StyledText {
            id: collectorErrorText
            x: 10; y: 10; width: parent.width - 20
            textFormat: Text.PlainText
            text: root.collectorError
            color: Theme.surfaceText
            font.pixelSize: Math.round(Theme.fontScale * 11)
            wrapMode: Text.Wrap
        }
    }

    Flickable {
        id: scroll
        objectName: "usageScroll"
        // DMS's scrollbar also supports its custom momentum-scrolling containers.
        readonly property bool isMomentumActive: flicking
        width: parent.width - root.padding * 2
        height: Math.min(root.maxBodyHeight, columns.implicitHeight)
        contentHeight: columns.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: DankScrollbar {
            objectName: "usageScrollbar"
            targetFlickable: scroll
        }
        onContentHeightChanged: contentY = Math.min(contentY, Math.max(0, contentHeight - height))
        Row {
            id: columns
            width: scroll.width
            spacing: 14
            Repeater {
                model: root.providers
                ProviderColumn {
                    required property var modelData
                    objectName: "providerColumn-" + modelData
                    width: root.columnWidth
                    provider: modelData
                    accounts: Usage.providerAccounts(root.snapshot, modelData)
                    now: root.now
                    showPacing: root.showPacing
                    degraded: root.collectorError !== ""
                    onDashboardRequested: url => {
                        root.dashboardRequested(url);
                        if (root.closePopout)
                            root.closePopout();
                    }
                }
            }
        }
    }

    StyledText {
        objectName: "usageFootnote"
        width: parent.width - root.padding * 2
        text: Usage.sharedNote(root.snapshot) || "Account-wide usage per subscription."
        visible: text !== ""
        color: Theme.surfaceVariantText
        font.pixelSize: Math.round(Theme.fontScale * 10.5)
        wrapMode: Text.Wrap
    }
}
