import QtQuick
import qs.Common
import qs.Widgets

Item {
    id: root
    property var value: null
    property real expected: -1
    property color accent: Theme.primary
    property bool showText: true
    property bool stale: false
    property int strokeWidth: width > 50 ? 7 : 3
    readonly property bool known: typeof value === "number" && isFinite(value)
    implicitWidth: 84
    implicitHeight: implicitWidth

    Canvas {
        id: canvas
        anchors.fill: parent
        property color track: Theme.surfaceVariant
        onTrackChanged: requestPaint()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            var radius = Math.min(width, height) / 2 - root.strokeWidth;
            if (radius <= 0)
                return;
            ctx.lineWidth = root.strokeWidth;
            ctx.strokeStyle = track;
            ctx.beginPath();
            ctx.arc(width / 2, height / 2, radius, 0, Math.PI * 2);
            ctx.stroke();
            if (root.known && root.value > 0) {
                ctx.strokeStyle = root.accent;
                ctx.lineCap = "round";
                ctx.globalAlpha = root.stale ? 0.55 : 1;
                ctx.beginPath();
                ctx.arc(width / 2, height / 2, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * Math.min(root.value, 100) / 100);
                ctx.stroke();
                ctx.globalAlpha = 1;
            }
            if (root.expected >= 0 && root.known) {
                var angle = -Math.PI / 2 + Math.PI * 2 * root.expected / 100;
                ctx.strokeStyle = Theme.surfaceText;
                ctx.lineWidth = 2;
                ctx.lineCap = "butt";
                ctx.beginPath();
                ctx.moveTo(width / 2 + Math.cos(angle) * (radius - root.strokeWidth), height / 2 + Math.sin(angle) * (radius - root.strokeWidth));
                ctx.lineTo(width / 2 + Math.cos(angle) * (radius + root.strokeWidth), height / 2 + Math.sin(angle) * (radius + root.strokeWidth));
                ctx.stroke();
            }
        }
    }
    onValueChanged: canvas.requestPaint()
    onExpectedChanged: canvas.requestPaint()
    onAccentChanged: canvas.requestPaint()
    onStaleChanged: canvas.requestPaint()
    onStrokeWidthChanged: canvas.requestPaint()

    StyledText {
        anchors.centerIn: parent
        visible: root.showText
        text: root.known ? Math.round(root.value) + "%" : "—"
        font.pixelSize: Math.round(Theme.fontScale * (root.width > 65 ? 23 : 16))
        font.weight: Font.Medium
        color: Theme.surfaceText
    }
}
