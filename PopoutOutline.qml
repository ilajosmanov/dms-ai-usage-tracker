import QtQuick
import qs.Common

// Attach to the shell's surface loader, outside the plugin's content padding.
// This follows the surface animation and never intercepts pointer events.
Canvas {
    id: root
    required property var popout
    parent: popout ? popout.contentLoader : null
    visible: popout !== null
    z: 100
    readonly property bool connected: popout !== null && popout.useConnectedBackend && Theme.isConnectedEffect
    readonly property vector4d radii: popout ? popout.surfaceCornerRadii : Qt.vector4d(0, 0, 0, 0)
    readonly property int side: popout ? popout.effectiveBarPosition : 0
    readonly property bool horizontal: side < 2
    readonly property real bodyWidth: parent ? parent.width : 0
    readonly property real bodyHeight: parent ? parent.height : 0
    readonly property real corner: connected ? Theme.connectedCornerRadius : Theme.windowRadius
    readonly property color outlineColor: Theme.withAlpha(Theme.surfaceText, 0.22)
    x: connected && horizontal ? -corner : 0
    y: connected && !horizontal ? -corner : 0
    width: bodyWidth + (connected && horizontal ? corner * 2 : 0)
    height: bodyHeight + (connected && !horizontal ? corner * 2 : 0)
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onSideChanged: requestPaint()
    onConnectedChanged: requestPaint()
    onCornerChanged: requestPaint()
    onOutlineColorChanged: requestPaint()
    onRadiiChanged: requestPaint()

    onPaint: {
        var ctx = getContext("2d");
        ctx.reset();
        ctx.clearRect(0, 0, width, height);
        ctx.strokeStyle = outlineColor;
        ctx.lineWidth = 1;
        ctx.beginPath();
        if (connected) {
            // Draw a top-attached contour, then rotate/reflect for the bar side.
            // Leave the attachment edge open where the surface joins the bar.
            if (side === 0) ctx.translate(corner, 0);
            else if (side === 1) { ctx.translate(corner, bodyHeight); ctx.scale(1, -1); }
            else if (side === 2) { ctx.translate(0, corner); ctx.transform(0, 1, 1, 0, 0, 0); }
            else { ctx.translate(bodyWidth, corner); ctx.transform(0, 1, -1, 0, 0, 0); }
            var w = horizontal ? bodyWidth : bodyHeight;
            var h = horizontal ? bodyHeight : bodyWidth;
            var r = Math.min(corner, w / 2, h / 2);
            var k = 0.55228475;
            ctx.moveTo(-r, 0.5);
            ctx.bezierCurveTo(-r + k * r, 0.5, 0.5, r - k * r, 0.5, r);
            ctx.lineTo(0.5, h - r);
            ctx.bezierCurveTo(0.5, h - r + k * r, r - k * r, h - 0.5, r, h - 0.5);
            ctx.lineTo(w - r, h - 0.5);
            ctx.bezierCurveTo(w - r + k * r, h - 0.5, w - 0.5, h - r + k * r, w - 0.5, h - r);
            ctx.lineTo(w - 0.5, r);
            ctx.bezierCurveTo(w - 0.5, r - k * r, w + r - k * r, 0.5, w + r, 0.5);
        } else {
            var w = bodyWidth - 0.5, h = bodyHeight - 0.5;
            var tl = Math.min(radii.x, w / 2, h / 2);
            var tr = Math.min(radii.y, w / 2, h / 2);
            var br = Math.min(radii.z, w / 2, h / 2);
            var bl = Math.min(radii.w, w / 2, h / 2);
            var k = 0.55228475;
            ctx.moveTo(tl, 0.5);
            ctx.lineTo(w - tr, 0.5);
            ctx.bezierCurveTo(w - tr + k * tr, 0.5, w, tr - k * tr, w, tr);
            ctx.lineTo(w, h - br);
            ctx.bezierCurveTo(w, h - br + k * br, w - br + k * br, h, w - br, h);
            ctx.lineTo(bl, h);
            ctx.bezierCurveTo(bl - k * bl, h, 0.5, h - bl + k * bl, 0.5, h - bl);
            ctx.lineTo(0.5, tl);
            ctx.bezierCurveTo(0.5, tl - k * tl, tl - k * tl, 0.5, tl, 0.5);
            ctx.closePath();
        }
        ctx.stroke();
    }
}
