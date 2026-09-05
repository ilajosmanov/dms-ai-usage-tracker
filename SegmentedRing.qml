import QtQuick
import qs.Common
import "Usage.js" as Usage

Canvas {
    id: root
    property var codex: ({windows: [], status: "missing"})
    property var claude: ({windows: [], status: "missing"})
    property bool failed: false
    property color unknownColor: Theme.surfaceVariantText
    readonly property color codexColor: Usage.accent("codex")
    readonly property color claudeColor: Usage.accent("claude")
    readonly property var segments: Usage.ringSegments(codex, claude)
    onSegmentsChanged: requestPaint()
    implicitWidth: 26
    implicitHeight: 26
    onFailedChanged: requestPaint()
    onUnknownColorChanged: requestPaint()
    onCodexColorChanged: requestPaint()
    onClaudeColorChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: {
        var ctx = getContext("2d");
        ctx.reset();
        var radius = Math.min(width, height) / 2 - 3;
        if (radius <= 0) return;
        ctx.lineWidth = 3;
        ctx.lineCap = "butt";
        for (var i = 0; i < segments.length; i++) {
            var segment = segments[i];
            var known = segment.used !== null;
            var start = segment.start;
            var span = segment.sweep;
            ctx.strokeStyle = known ? (segment.provider === "codex" ? codexColor : claudeColor) : unknownColor;
            ctx.globalAlpha = known ? (failed || segment.stale ? 0.5 : 1) : 0.35;
            ctx.beginPath();
            ctx.arc(width / 2, height / 2, radius, start, start + span);
            ctx.stroke();
        }
        ctx.globalAlpha = 1;
    }
}
