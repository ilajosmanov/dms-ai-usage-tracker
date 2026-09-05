import QtQuick
import QtQuick.Controls
import qs.Common
import qs.Widgets
import "Usage.js" as Usage

Column {
    id: root
    property var snapshot: ({accounts: []})
    property string provider: "codex"
    property string accountId: ""
    property bool loading: false
    property string collectorError: ""
    property bool showPacing: true
    property real now: Date.now()
    property real maxBodyHeight: 650
    property var closePopout: null
    signal refreshRequested()
    signal providerSelected(string provider)
    signal dashboardRequested(string url)
    readonly property var accounts: Usage.providerAccounts(snapshot, provider)
    readonly property var account: accounts.filter(function(a) { return a.id === root.accountId; })[0] || Usage.representativeAccount(accounts) || ({windows: [], history: [], status: "loading", name: "", label: "", plan: "", message: "", sources: []})
    readonly property var windows: account.windows || []
    readonly property color providerColor: Usage.accent(provider)
    readonly property color cautionColor: Theme.isLightMode ? Qt.darker(Theme.warning, 1.8) : Theme.warning
    padding: 12
    spacing: 16
    width: 408

    Row {
        id: header
        objectName: "usageHeader"
        width: parent.width - root.padding * 2
        height: 48
        Column {
            width: parent.width - 108
            anchors.verticalCenter: parent.verticalCenter
            spacing: 3
            StyledText {
                width: parent.width
                text: root.snapshot.demo ? "AI Usage · Demo" : "AI Usage"
                font.pixelSize: Math.round(Theme.fontScale * 23)
                font.weight: Font.Medium
                color: Theme.surfaceText
                elide: Text.ElideRight
            }
            StyledText {
                objectName: "updatedLabel"
                width: parent.width
                text: root.loading ? "Checking…" : Usage.age(root.account.updatedAt, root.now)
                color: Theme.surfaceVariantText
                font.pixelSize: Math.round(Theme.fontScale * 11)
                elide: Text.ElideRight
            }
        }
        ToolButton {
            objectName: "dashboardButton"
            width: 36; height: 36
            anchors.verticalCenter: parent.verticalCenter
            Accessible.name: "Open provider dashboard"
            UsageTooltip { visible: parent.hovered; text: "Open dashboard" }
            background: Rectangle { radius: 18; color: parent.hovered ? Theme.surfaceContainerHigh : "transparent" }
            contentItem: DankIcon { name: "open_in_new"; size: 20; color: Theme.surfaceText }
            onClicked: {
                root.dashboardRequested(Usage.dashboardUrl(root.provider));
                if (root.closePopout) root.closePopout();
            }
        }
        ToolButton {
            objectName: "refreshButton"
            width: 36; height: 36
            anchors.verticalCenter: parent.verticalCenter
            enabled: !root.loading
            Accessible.name: "Refresh usage"
            UsageTooltip { visible: parent.hovered; text: "Refresh usage" }
            background: Rectangle { radius: 18; color: parent.hovered ? Theme.surfaceContainerHigh : "transparent" }
            contentItem: DankIcon { name: "refresh"; size: 20; color: root.loading ? Theme.surfaceVariantText : Theme.surfaceText }
            onClicked: root.refreshRequested()
        }
        ToolButton {
            width: 36; height: 36
            anchors.verticalCenter: parent.verticalCenter
            Accessible.name: "Close usage"
            UsageTooltip { visible: parent.hovered; text: "Close" }
            background: Rectangle { radius: 18; color: parent.hovered ? Theme.surfaceContainerHigh : "transparent" }
            contentItem: DankIcon { name: "close"; size: 20; color: Theme.surfaceText }
            onClicked: { if (root.closePopout) root.closePopout(); }
        }
    }

    Rectangle {
        width: parent.width - root.padding * 2
        height: 38
        radius: Theme.cornerRadius
        color: Theme.surfaceContainerHigh
        Row {
            anchors.fill: parent
            anchors.margins: 3
            Repeater {
                model: Usage.tabs()
                ToolButton {
                    required property var modelData
                    width: parent.width / 2; height: parent.height
                    Accessible.name: modelData.label
                    Accessible.role: Accessible.PageTab
                    Accessible.selected: root.provider === modelData.id
                    background: Rectangle {
                        radius: Math.max(2, Theme.cornerRadius - 3)
                        color: root.provider === parent.modelData.id ? Theme.surfaceVariant : parent.hovered ? Theme.withAlpha(Theme.surfaceText, 0.06) : "transparent"
                    }
                    contentItem: Item {
                        Row {
                            anchors.centerIn: parent
                            spacing: 7
                            Rectangle {
                                anchors.verticalCenter: parent.verticalCenter
                                width: 7; height: 7; radius: 4
                                color: Usage.accent(modelData.id)
                            }
                            StyledText {
                                text: modelData.label
                                color: root.provider === modelData.id ? Theme.surfaceText : Theme.surfaceVariantText
                                font.pixelSize: Math.round(Theme.fontScale * 14); font.weight: Font.Medium
                            }
                        }
                    }
                    onClicked: {
                        root.provider = modelData.id;
                        root.accountId = "";
                        root.providerSelected(modelData.id);
                    }
                }
            }
        }
    }

    Flickable {
        id: scroll
        objectName: "usageScroll"
        // DMS's scrollbar also supports its custom momentum-scrolling containers.
        readonly property bool isMomentumActive: flicking
        width: parent.width - root.padding * 2
        height: Math.min(root.maxBodyHeight, body.implicitHeight)
        contentHeight: body.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: DankScrollbar {
            objectName: "usageScrollbar"
            targetFlickable: scroll
        }
        onContentHeightChanged: contentY = Math.min(contentY, Math.max(0, contentHeight - height))
        Column {
            id: body
            width: scroll.width - (scroll.contentHeight > scroll.height ? 14 : 0)
            spacing: 16

            Column {
                width: parent.width
                spacing: 5
                StyledText {
                    width: parent.width
                    objectName: "subscriptionTitle"
                    textFormat: Text.PlainText
                    text: root.account.name + (root.account.plan && root.account.plan !== root.account.name ? " · " + Usage.planLabel(root.account.plan) : "")
                    color: Theme.surfaceText
                    font.pixelSize: Math.round(Theme.fontScale * 15)
                    font.weight: Font.Medium
                    elide: Text.ElideRight
                }
                StyledText {
                    width: parent.width
                    textFormat: Text.PlainText
                    text: Usage.clientLabel(root.account.label) || "Finding accounts…"
                    font.pixelSize: Math.round(Theme.fontScale * 12)
                    color: Theme.surfaceVariantText
                    wrapMode: Text.Wrap
                }
            }

            DankDropdown {
                objectName: "accountSelector"
                width: parent.width
                visible: root.accounts.length > 1
                text: "Account"
                options: root.accounts.map(function(a) { return Usage.clientLabel(a.label); })
                currentValue: Usage.clientLabel(root.account.label)
                onValueChanged: value => {
                    var selected = root.accounts.filter(function(a) { return Usage.clientLabel(a.label) === value; })[0];
                    if (selected) root.accountId = selected.id;
                }
            }

            Rectangle {
                width: parent.width
                implicitHeight: statusColumn.implicitHeight + 32
                radius: Theme.cornerRadius
                color: Theme.surfaceContainerHigh
                visible: root.account.status !== "ok" || root.collectorError !== ""
                Column {
                    id: statusColumn
                    x: 16; y: 16; width: parent.width - 32
                    spacing: 6
                    StyledText {
                        text: root.collectorError ? "Could not refresh" : root.account.status === "stale" ? "Showing saved usage" : root.account.status === "missing" ? "Connect " + root.account.name : root.account.status === "auth" ? "Sign-in needed" : root.account.status === "loading" ? "Checking your accounts…" : "Usage unavailable"
                        color: Theme.surfaceText
                        font.pixelSize: Math.round(Theme.fontScale * 15); font.weight: Font.Medium
                    }
                    StyledText {
                        width: parent.width
                        textFormat: Text.PlainText
                        text: root.collectorError || root.account.message || "Reading your connected providers."
                        color: Theme.surfaceVariantText
                        font.pixelSize: Math.round(Theme.fontScale * 13)
                        wrapMode: Text.Wrap
                    }
                }
            }

            Repeater {
                model: root.windows
                Rectangle {
                    id: windowCard
                    required property var modelData
                    required property int index
                    readonly property var pacing: root.showPacing ? Usage.pace(modelData, root.now) : null
                    width: body.width
                    height: index === 0 ? 120 : 108
                    radius: Theme.cornerRadius
                    color: Theme.surfaceContainerHigh
                    UsageRing {
                        id: ring
                        x: 16
                        anchors.verticalCenter: parent.verticalCenter
                        width: windowCard.index === 0 ? 86 : 68
                        height: width
                        value: windowCard.modelData.used
                        expected: windowCard.pacing ? windowCard.pacing.expected : -1
                        accent: root.providerColor
                        stale: root.account.status === "stale" || root.collectorError !== ""
                    }
                    Column {
                        x: ring.x + ring.width + 16
                        width: parent.width - x - 16
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 5
                        StyledText {
                            width: parent.width
                            textFormat: Text.PlainText
                            text: windowCard.modelData.label
                            color: Theme.surfaceText
                            font.pixelSize: Math.round(Theme.fontScale * 14)
                            elide: Text.ElideRight
                        }
                        StyledText {
                            text: Usage.percent(windowCard.modelData) + " used"
                            color: root.providerColor
                            font.pixelSize: Math.round(Theme.fontScale * 14)
                            font.weight: Font.Medium
                        }
                        StyledText {
                            visible: windowCard.pacing !== null
                            text: windowCard.pacing ? windowCard.pacing.text : ""
                            color: windowCard.pacing && windowCard.pacing.delta >= 2 ? root.cautionColor : Theme.surfaceVariantText
                            font.pixelSize: Math.round(Theme.fontScale * 12)
                        }
                        StyledText {
                            text: Usage.countdown(windowCard.modelData.resetAt, root.now)
                            color: Theme.surfaceVariantText
                            font.pixelSize: Math.round(Theme.fontScale * 12)
                        }
                    }
                }
            }

            Rectangle {
                width: parent.width
                height: 168
                radius: Theme.cornerRadius
                color: Theme.surfaceContainerHigh
                visible: (root.account.history || []).length > 0
                Column {
                    x: 16; y: 16; width: parent.width - 32
                    spacing: 9
                    StyledText {
                        textFormat: Text.PlainText
                        text: "Daily peak · " + (root.windows[0] ? root.windows[0].label : "usage")
                        width: parent.width
                        elide: Text.ElideRight
                        color: Theme.surfaceText
                        font.pixelSize: Math.round(Theme.fontScale * 14)
                    }
                    Row {
                        id: chart
                        width: parent.width
                        height: 88
                        spacing: 10
                        readonly property var days: Usage.days(root.account.history, root.now, root.account.modelsByDay || ({}))
                        readonly property real maximum: 100
                        Repeater {
                            model: chart.days
                            Item {
                                id: dayItem
                                objectName: "dailyPeakColumn-" + index
                                required property var modelData
                                required property int index
                                width: (chart.width - 60) / 7
                                height: 88
                                Accessible.name: Usage.dayTooltip(dayItem.modelData).replace(/\n/g, "; ")
                                HoverHandler { id: dayColumnHover }
                                Rectangle {
                                    id: dayBar
                                    objectName: "dailyPeakBar-" + dayItem.index
                                    width: parent.width
                                    height: dayItem.modelData.value === null ? 2 : Math.max(2, 64 * Math.min(1, Math.max(0, dayItem.modelData.value) / chart.maximum))
                                    y: 64 - height
                                    radius: 2
                                    color: dayItem.modelData.value === null ? Theme.withAlpha(Theme.surfaceText, 0.08) : dayItem.index === 6 ? root.providerColor : Theme.withAlpha(root.providerColor, 0.3)
                                    UsageTooltip {
                                        objectName: "dailyPeakTooltip-" + dayItem.index
                                        visible: dayColumnHover.hovered
                                        text: Usage.dayTooltip(dayItem.modelData)
                                    }
                                }
                                StyledText {
                                    y: 71; width: parent.width
                                    text: dayItem.modelData.label
                                    color: Theme.surfaceVariantText
                                    horizontalAlignment: Text.AlignHCenter
                                    font.pixelSize: Math.round(Theme.fontScale * 11)
                                }
                            }
                        }
                    }
                    StyledText {
                        text: "Last 7 days · recorded by this widget"
                        color: Theme.surfaceVariantText
                        font.pixelSize: Math.round(Theme.fontScale * 11)
                    }
                }
            }

            StyledText {
                width: parent.width
                textFormat: Text.PlainText
                text: root.account.note || ""
                visible: text !== ""
                color: Theme.surfaceVariantText
                font.pixelSize: Math.round(Theme.fontScale * 12)
                wrapMode: Text.Wrap
            }
        }
    }
}
