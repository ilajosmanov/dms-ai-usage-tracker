import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Common
import qs.DCommon.Common as DC
import qs.Plugin
import "Plugin/Usage.js" as Usage

// Registry preview capture: the bar pill and the popout it opens, side by side,
// on real collector output and the stock dank theme.
ShellRoot {
    id: capture
    Component.onCompleted: {
        DC.Style.theme = Theme;
        DC.Style.settings = SettingsData;
    }
    property var data: ({accounts: []})
    property bool ready: false

    // Supply the same public surface geometry used by PluginPopout, so this
    // standalone capture includes the actual outer outline and shell padding.
    QtObject {
        id: previewSurface
        readonly property var contentLoader: popout
        readonly property bool useConnectedBackend: false
        readonly property int effectiveBarPosition: 1
        readonly property vector4d surfaceCornerRadii: Qt.vector4d(popout.radius, popout.radius, popout.radius, popout.radius)
    }

    Process {
        command: ["python3", decodeURIComponent(Qt.resolvedUrl("Plugin/get-ai-usage").toString().replace("file://", ""))]
        running: true
        stdout: StdioCollector {
            onStreamFinished: {
                capture.data = JSON.parse(text);
                capture.ready = true;
                settle.start();
            }
        }
    }

    FloatingWindow {
        id: window
        title: "Subscription Usage Meter"
        visible: true
        implicitWidth: frame.width
        implicitHeight: frame.height
        minimumSize: Qt.size(frame.width, frame.height)
        maximumSize: minimumSize
        color: Theme.surfaceContainer

        Rectangle {
            id: frame
            width: 456
            height: Math.ceil(bar.height + 14 + popout.height)
            color: "transparent"

            // A bar strip the width of the frame, with the pill sitting in it the
            // way it sits in DankBar.
            Rectangle {
                id: bar
                width: parent.width
                height: 36
                radius: 10
                color: Theme.surfaceContainerHigh
                AIUsagePill {
                    id: pill
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.right: parent.right
                    anchors.rightMargin: 12
                    snapshot: capture.data
                }
            }

            Rectangle {
                id: popout
                anchors.top: bar.bottom
                anchors.topMargin: 14
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width
                height: Math.ceil(dashboard.implicitHeight + PopoutMetrics.contentPadding * 2)
                radius: Theme.windowRadius
                color: Theme.readableSurface
                UsageDashboard {
                    id: dashboard
                    x: PopoutMetrics.contentPadding
                    y: PopoutMetrics.contentPadding
                    width: parent.width - PopoutMetrics.contentPadding * 2
                    parentPopout: previewSurface
                    snapshot: capture.data
                    primaryProvider: "codex"
                    maxBodyHeight: 1000
                    closePopout: () => {}
                }
            }
        }
    }

    Timer {
        id: settle
        interval: 600
        onTriggered: {
            frame.grabToImage(function(result) {
                result.saveToFile(Quickshell.env("AI_USAGE_CAPTURE_OUT"));
                console.log("AI_USAGE_CAPTURE_COMPLETE " + frame.width + "x" + frame.height);
                Qt.exit(0);
            });
        }
    }
}
