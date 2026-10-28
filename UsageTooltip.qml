import QtQuick
import qs.DCommon.Widgets

DTooltipHost {
    id: root
    property var pointer: null
    multiline: true
    side: pointer ? "top" : "bottom"
    target: pointer ? cursorTarget : parent

    onVisibleChanged: {
        if (visible)
            Qt.callLater(schedule);
        else
            dismiss();
    }
    Component.onCompleted: { if (visible) Qt.callLater(schedule); }

    // Keep row tooltips near the pointer while using DMS placement and styling.
    Item {
        id: cursorTarget
        x: root.pointer ? root.pointer.point.position.x : 0
        y: root.pointer ? root.pointer.point.position.y : 0
        width: 1
        height: 1
        visible: root.visible
        onXChanged: root.refresh()
        onYChanged: root.refresh()
    }
}
