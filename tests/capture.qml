import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Common
import qs.Plugin
import "Plugin/Usage.js" as Usage

// Registry preview capture: the bar pill and the popout it opens, side by side,
// on real collector output and the stock dank theme.
ShellRoot {
    id: capture
    property var data: ({accounts: []})
    property bool ready: false

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
        implicitWidth: 560
        implicitHeight: 760
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
                width: dashboard.width
                height: Math.ceil(dashboard.implicitHeight)
                radius: 20
                color: Theme.surfaceContainer
                UsageDashboard {
                    id: dashboard
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
                Quickshell.quit();
            });
        }
    }
}
