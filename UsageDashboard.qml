import QtQuick
import QtQuick.Controls
import qs.Common
import qs.DCommon.Widgets
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
    property var parentPopout: null
    signal refreshRequested()
    signal dashboardRequested(string url)
    // Column order only; both providers are always on screen.
    readonly property var providers: Usage.orderedProviders(primaryProvider)
    readonly property real columnWidth: (width - padding * 2 - columns.spacing) / 2
    padding: Theme.spacingM
    spacing: Theme.spacingM
    width: 424

    PopoutOutline { popout: root.parentPopout }

    Item {
        id: header
        objectName: "usageHeader"
        width: parent.width - root.padding * 2
        height: Math.max(Theme.spacingXL, headerActions.implicitHeight)
        StyledText {
            anchors.left: parent.left
            anchors.right: headerActions.left
            anchors.rightMargin: Theme.spacingS
            anchors.verticalCenter: parent.verticalCenter
            elide: Text.ElideRight
            text: root.snapshot.demo ? "Subscription Usage Meter · Demo" : "Subscription Usage Meter"
            color: Theme.surfaceText
            font.pixelSize: Theme.fontSizeMedium
            font.weight: Font.Medium
        }
        Row {
            id: headerActions
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.spacingXS
            StyledText {
                objectName: "updatedLabel"
                anchors.verticalCenter: parent.verticalCenter
                rightPadding: Theme.spacingXS
                text: root.loading ? "Checking…" : Usage.age(Usage.latestUpdate(root.snapshot), root.now)
                color: Theme.surfaceVariantText
                font.pixelSize: Theme.fontSizeSmall
            }
            DActionButton {
                objectName: "refreshButton"
                width: Theme.spacingXL; height: Theme.spacingXL
                anchors.verticalCenter: parent.verticalCenter
                enabled: !root.loading
                Accessible.name: "Refresh usage"
                tooltipText: "Refresh usage"
                iconName: "refresh"
                iconSize: Theme.fontSizeLarge
                iconColor: Theme.surfaceText
                onClicked: root.refreshRequested()
            }
            DActionButton {
                objectName: "closeButton"
                width: Theme.spacingXL; height: Theme.spacingXL
                anchors.verticalCenter: parent.verticalCenter
                Accessible.name: "Close usage"
                tooltipText: "Close"
                iconName: "close"
                iconSize: Theme.fontSizeLarge
                iconColor: Theme.surfaceText
                onClicked: { if (root.closePopout) root.closePopout(); }
            }
        }
    }

    Rectangle {
        objectName: "collectorErrorCard"
        width: parent.width - root.padding * 2
        implicitHeight: collectorErrorText.implicitHeight + Theme.spacingS * 2
        radius: Theme.cornerRadius
        color: Theme.surfaceContainerHigh
        visible: root.collectorError !== ""
        StyledText {
            id: collectorErrorText
            x: Theme.spacingS; y: Theme.spacingS; width: parent.width - Theme.spacingS * 2
            textFormat: Text.PlainText
            text: root.collectorError
            color: Theme.surfaceText
            font.pixelSize: Theme.fontSizeSmall
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
        ScrollBar.vertical: DScrollbar {
            objectName: "usageScrollbar"
            targetFlickable: scroll
        }
        onContentHeightChanged: contentY = Math.min(contentY, Math.max(0, contentHeight - height))
        Row {
            id: columns
            width: scroll.width
            spacing: Theme.spacingL
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
        font.pixelSize: Theme.fontSizeSmall
        wrapMode: Text.Wrap
    }
}
