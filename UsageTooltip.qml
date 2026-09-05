import QtQuick
import QtQuick.Controls
import qs.Common
import qs.Widgets

ToolTip {
    id: root
    popupType: Popup.Window
    delay: 350
    padding: Theme.spacingM
    contentItem: StyledText {
        textFormat: Text.PlainText
        text: root.text
        color: Theme.surfaceText
        font.pixelSize: Theme.fontSizeSmall
    }
    background: Rectangle {
        color: Theme.surfaceContainerHigh
        radius: Theme.cornerRadius
        border.color: Theme.outline
    }
}
