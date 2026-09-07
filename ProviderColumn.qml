import QtQuick
import QtQuick.Controls
import qs.Common
import qs.Widgets
import "Usage.js" as Usage

// One provider owns one column: its plan, its limits, its week and its models.
// Nothing in here is shared with the other provider, because the two
// subscriptions are separate allowances and must never read as one pool.
Column {
    id: root
    property string provider: "codex"
    property var accounts: []
    property real now: Date.now()
    property bool showPacing: true
    property bool degraded: false
    property string accountId: ""
    signal dashboardRequested(string url)

    readonly property var account: accounts.filter(function(a) { return a.id === root.accountId; })[0]
        || Usage.representativeAccount(accounts)
        || ({windows: [], history: [], models: [], status: "loading", name: "", label: "", plan: "", message: ""})
    readonly property var windows: account.windows || []
    readonly property var models: Usage.modelBars(account)
    readonly property bool stale: degraded || account.status === "stale"
    readonly property color accent: Usage.accent(provider)
    readonly property color accentText: Usage.accentText(provider, Theme.isLightMode)
    readonly property color cautionColor: Theme.isLightMode ? Qt.darker(Theme.warning, 1.8) : Theme.warning
    readonly property color hairline: Theme.withAlpha(Theme.surfaceText, 0.12)
    readonly property color trackColor: Theme.withAlpha(Theme.surfaceText, 0.1)
    spacing: 9

    Item {
        objectName: "columnHeader-" + root.provider
        width: parent.width
        height: 20
        Row {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - 26
            spacing: 6
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: 7; height: 7; radius: 4
                color: root.accent
                opacity: root.stale ? 0.5 : 1
            }
            StyledText {
                objectName: "columnTitle-" + root.provider
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: root.account.name || Usage.brandLabel(root.provider)
                color: Theme.surfaceText
                font.pixelSize: Math.round(Theme.fontScale * 14)
                font.weight: Font.Medium
            }
            StyledText {
                objectName: "columnPlan-" + root.provider
                anchors.verticalCenter: parent.verticalCenter
                width: Math.max(0, parent.width - x)
                textFormat: Text.PlainText
                text: Usage.shortPlan(root.account.plan, root.account.name)
                color: Theme.surfaceVariantText
                font.pixelSize: Math.round(Theme.fontScale * 11)
                elide: Text.ElideRight
            }
        }
        ToolButton {
            objectName: "dashboardButton-" + root.provider
            padding: 0
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: 22; height: 22
            Accessible.name: "Open the " + Usage.brandLabel(root.provider) + " usage dashboard"
            UsageTooltip { visible: parent.hovered; text: "Open " + Usage.brandLabel(root.provider) + " dashboard" }
            background: Rectangle {
                radius: 10
                color: parent.hovered ? Theme.surfaceContainerHigh : "transparent"
            }
            contentItem: DankIcon { name: "open_in_new"; size: 14; color: parent.hovered ? Theme.surfaceText : Theme.surfaceVariantText }
            onClicked: root.dashboardRequested(Usage.dashboardUrl(root.provider))
        }
    }

    Rectangle {
        width: parent.width
        height: 1
        color: root.hairline
    }

    StyledText {
        objectName: "clientLabel-" + root.provider
        width: parent.width
        textFormat: Text.PlainText
        text: Usage.clientLabel(root.account.label) || (root.account.status === "loading" ? "Finding accounts…" : "")
        // The selector already names the account, so don't print it twice.
        visible: text !== "" && root.accounts.length < 2
        color: Theme.surfaceVariantText
        font.pixelSize: Math.round(Theme.fontScale * 11)
        wrapMode: Text.Wrap
        maximumLineCount: 2
        elide: Text.ElideRight
    }

    DankDropdown {
        objectName: "accountSelector-" + root.provider
        visible: root.accounts.length > 1
        text: ""
        dropdownWidth: root.width
        popupWidth: root.width
        options: root.accounts.map(function(a) { return Usage.clientLabel(a.label); })
        currentValue: Usage.clientLabel(root.account.label)
        onValueChanged: value => {
            var selected = root.accounts.filter(function(a) { return Usage.clientLabel(a.label) === value; })[0];
            if (selected)
                root.accountId = selected.id;
        }
    }

    // The only filled surface in the panel, so a fill means "needs attention"
    // instead of meaning "section". Per column, because Codex can be signed in
    // while Claude is not.
    Rectangle {
        objectName: "statusCard-" + root.provider
        width: parent.width
        implicitHeight: statusColumn.implicitHeight + 20
        radius: Theme.cornerRadius
        color: Theme.surfaceContainerHigh
        visible: root.account.status !== "ok"
        Column {
            id: statusColumn
            x: 10; y: 10; width: parent.width - 20
            spacing: 3
            StyledText {
                width: parent.width
                text: root.account.status === "stale" ? "Showing saved usage"
                    : root.account.status === "missing" ? "Not connected"
                    : root.account.status === "auth" ? "Sign-in needed"
                    : root.account.status === "loading" ? "Checking…"
                    : "Usage unavailable"
                color: Theme.surfaceText
                font.pixelSize: Math.round(Theme.fontScale * 12)
                font.weight: Font.Medium
                wrapMode: Text.Wrap
            }
            StyledText {
                width: parent.width
                textFormat: Text.PlainText
                text: root.account.message || ""
                visible: text !== ""
                color: Theme.surfaceVariantText
                font.pixelSize: Math.round(Theme.fontScale * 11)
                wrapMode: Text.Wrap
            }
        }
    }

    Repeater {
        model: root.windows
        Column {
            id: limit
            required property var modelData
            required property int index
            objectName: "limit-" + root.provider + "-" + index
            readonly property var pacing: root.showPacing ? Usage.pace(modelData, root.now) : null
            readonly property bool overPace: pacing !== null && pacing.delta >= 2
            readonly property bool known: typeof modelData.used === "number" && isFinite(modelData.used)
            width: root.width
            spacing: 3
            Accessible.name: modelData.label + ": " + Usage.percent(modelData) + " used"
                + (pacing ? ", " + pacing.text : "") + ", " + Usage.countdown(modelData.resetAt, root.now)
            HoverHandler { id: limitHover }
            UsageTooltip {
                objectName: "limitTooltip-" + root.provider + "-" + limit.index
                pointer: limitHover
                visible: limitHover.hovered
                // Only what the row could not say: the unshortened label, and
                // the reset spelled out. The pace verdict is already on screen.
                text: limit.modelData.label + "\n" + Usage.percent(limit.modelData)
                    + " used · " + Usage.countdown(limit.modelData.resetAt, root.now)
            }

            Item {
                width: parent.width
                height: limitPercent.implicitHeight
                StyledText {
                    width: Math.max(0, parent.width - limitPercent.implicitWidth - 6)
                    textFormat: Text.PlainText
                    text: Usage.shortWindow(limit.modelData.label)
                    color: Theme.surfaceText
                    font.pixelSize: Math.round(Theme.fontScale * 12)
                    elide: Text.ElideRight
                }
                StyledText {
                    id: limitPercent
                    objectName: "limitPercent-" + root.provider + "-" + limit.index
                    anchors.right: parent.right
                    text: Usage.percent(limit.modelData)
                    // Brand tint says whose limit this is; caution says it is nearly gone.
                    color: Usage.nearLimit(limit.modelData) ? root.cautionColor : root.accentText
                    font.pixelSize: Math.round(Theme.fontScale * 13)
                    font.weight: Font.Medium
                }
            }

            Rectangle {
                width: parent.width
                height: 5
                radius: 2.5
                color: root.trackColor
                Rectangle {
                    objectName: "limitFill-" + root.provider + "-" + limit.index
                    width: !limit.known || limit.modelData.used <= 0 ? 0
                        : Math.max(3, parent.width * Math.min(1, limit.modelData.used / 100))
                    height: parent.height
                    radius: parent.radius
                    color: root.accent
                    opacity: root.stale ? 0.55 : 1
                }
                Rectangle {
                    objectName: "paceTick-" + root.provider + "-" + limit.index
                    visible: limit.pacing !== null
                    x: Math.min(parent.width - 2, Math.max(0, parent.width * (limit.pacing ? limit.pacing.expected : 0) / 100))
                    y: -2
                    width: 2
                    height: parent.height + 4
                    radius: 1
                    color: Theme.surfaceText
                    opacity: 0.5
                }
            }

            Item {
                width: parent.width
                height: limitReset.implicitHeight
                StyledText {
                    objectName: "limitPace-" + root.provider + "-" + limit.index
                    width: Math.max(0, parent.width - limitReset.implicitWidth - 6)
                    visible: limit.pacing !== null
                    text: limit.pacing ? limit.pacing.text : ""
                    color: limit.overPace ? root.cautionColor : Theme.surfaceVariantText
                    font.pixelSize: Math.round(Theme.fontScale * 10.5)
                    elide: Text.ElideRight
                }
                StyledText {
                    id: limitReset
                    anchors.right: parent.right
                    text: Usage.resetShort(limit.modelData.resetAt, root.now)
                    color: Theme.surfaceVariantText
                    font.pixelSize: Math.round(Theme.fontScale * 10.5)
                }
            }
        }
    }

    StyledText {
        width: parent.width
        visible: root.windows.length === 0 && root.account.status === "ok"
        text: "No limits reported"
        color: Theme.surfaceVariantText
        font.pixelSize: Math.round(Theme.fontScale * 11)
    }

    Column {
        objectName: "weekBlock-" + root.provider
        width: parent.width
        spacing: 4
        visible: (root.account.history || []).length > 0
        StyledText {
            text: "Daily peak"
            color: Theme.surfaceVariantText
            font.pixelSize: Math.round(Theme.fontScale * 10.5)
        }
        Row {
            id: week
            width: parent.width
            height: 22
            spacing: 2
            readonly property var days: Usage.days(root.account.history, root.now)
            readonly property real cell: (width - spacing * 6) / 7
            Repeater {
                model: week.days
                Item {
                    id: day
                    objectName: "dailyPeakColumn-" + root.provider + "-" + index
                    required property var modelData
                    required property int index
                    width: week.cell
                    height: week.height
                    Accessible.name: Usage.dayTooltip(day.modelData)
                    HoverHandler { id: dayHover }
                    // Sibling of the handler, not a child of the bar: the
                    // tooltip's coordinates have to match the ones the handler
                    // reports, and the bar is bottom-anchored.
                    UsageTooltip {
                        objectName: "dailyPeakTooltip-" + root.provider + "-" + day.index
                        pointer: dayHover
                        visible: dayHover.hovered
                        text: Usage.dayTooltip(day.modelData)
                    }
                    Rectangle {
                        objectName: "dailyPeakBar-" + root.provider + "-" + day.index
                        anchors.bottom: parent.bottom
                        width: parent.width
                        height: day.modelData.value === null ? 2
                            : Math.max(2, parent.height * Math.min(1, Math.max(0, day.modelData.value) / 100))
                        radius: 2
                        color: day.modelData.value === null ? Theme.withAlpha(Theme.surfaceText, 0.08)
                            : day.index === 6 ? root.accent : Theme.withAlpha(root.accent, 0.34)
                    }
                }
            }
        }
        Row {
            width: parent.width
            spacing: 2
            Repeater {
                model: week.days
                StyledText {
                    required property var modelData
                    width: week.cell
                    text: modelData.label
                    color: Theme.surfaceVariantText
                    horizontalAlignment: Text.AlignHCenter
                    font.pixelSize: Math.round(Theme.fontScale * 9.5)
                }
            }
        }
    }

    Column {
        objectName: "modelsBlock-" + root.provider
        width: parent.width
        spacing: 4
        visible: root.models.length > 0
        StyledText {
            text: "Models this week"
            color: Theme.surfaceVariantText
            font.pixelSize: Math.round(Theme.fontScale * 10.5)
        }
        Repeater {
            model: root.models
            Column {
                id: modelRow
                required property var modelData
                required property int index
                objectName: "modelBar-" + root.provider + "-" + index
                width: root.width
                spacing: 2
                HoverHandler { id: modelHover }
                UsageTooltip {
                    pointer: modelHover
                    visible: modelHover.hovered
                    text: modelRow.modelData.name + "\n" + modelRow.modelData.label + " tokens processed on this machine"
                }
                Item {
                    width: parent.width
                    height: modelTokens.implicitHeight
                    StyledText {
                        objectName: "modelName-" + root.provider + "-" + modelRow.index
                        width: Math.max(0, parent.width - modelTokens.implicitWidth - 6)
                        textFormat: Text.PlainText
                        text: Usage.modelLabel(modelRow.modelData.name)
                        color: Theme.surfaceText
                        font.pixelSize: Math.round(Theme.fontScale * 11)
                        elide: Text.ElideRight
                    }
                    StyledText {
                        id: modelTokens
                        objectName: "modelTokens-" + root.provider + "-" + modelRow.index
                        anchors.right: parent.right
                        textFormat: Text.PlainText
                        text: modelRow.modelData.label
                        color: Theme.surfaceVariantText
                        font.pixelSize: Math.round(Theme.fontScale * 11)
                        font.weight: Font.Medium
                    }
                }
                Rectangle {
                    width: parent.width
                    height: 3
                    radius: 1.5
                    color: root.trackColor
                    Rectangle {
                        objectName: "modelBarFill-" + root.provider + "-" + modelRow.index
                        width: Math.max(2, parent.width * modelRow.modelData.share)
                        height: parent.height
                        radius: parent.radius
                        color: root.accent
                        opacity: 0.75
                    }
                }
            }
        }
    }
}
