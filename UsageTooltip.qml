import QtQuick
import QtQuick.Controls
import QtQuick.Window
import qs.Common
import qs.Widgets

ToolTip {
    id: root
    // Keep the tooltip in the popout's scene. A native tooltip window can be
    // reparented while the popout is resizing after a refresh; Qt 6.11 has a
    // crash in that Popup.Window transition (QQuickPopupPrivate).
    popupType: Popup.Item
    // A full-width row is a far bigger target than the pointer is precise, so
    // hand those rows their HoverHandler and the tooltip opens at the cursor.
    // Icon-sized targets leave it null and stay anchored under the button.
    property var pointer: null
    readonly property bool tracking: pointer !== null && pointer !== undefined
    readonly property int gap: 11
    readonly property int edge: 8
    // Flip rather than let Qt quietly shove an overflowing tooltip somewhere
    // else: a rows-wide column near the popout edge would otherwise land a long
    // way from the cursor that opened it.
    x: {
        if (!tracking || !parent)
            return Math.round((parent ? parent.width - width : 0) / 2);
        var local = Math.round(pointer.point.position.x);
        var scene = parent.mapToItem(null, local, 0).x;
        return scene + gap + width > parent.Window.width - edge ? local - width - gap : local + gap;
    }
    y: {
        if (!tracking || !parent)
            return parent ? parent.height + 4 : 0;
        var local = Math.round(pointer.point.position.y);
        var scene = parent.mapToItem(null, 0, local).y;
        return scene - height - 6 < edge ? local + 18 : local - height - 6;
    }
    margins: 6
    delay: 250
    padding: 0
    contentItem: StyledText {
        leftPadding: 6; rightPadding: 6; topPadding: 3; bottomPadding: 4
        textFormat: Text.PlainText
        text: root.text
        color: Theme.surfaceText
        font.pixelSize: Math.round(Theme.fontScale * 10.5)
        lineHeight: 1.2
        lineHeightMode: Text.ProportionalHeight
    }
    background: Rectangle {
        radius: 5
        color: Theme.surfaceContainerHighest
        border.width: 1
        border.color: Theme.withAlpha(Theme.surfaceText, 0.14)
    }
}
